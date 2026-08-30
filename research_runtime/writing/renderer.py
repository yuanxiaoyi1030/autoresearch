# Purpose: Materializes controlled conference-style LaTeX/BibTeX/Markdown and performs bounded PDF rendering QA.
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
from typing import Dict, Iterable, List, Tuple

from research_runtime.literature import LiteratureSource

from .models import (
    BuildCommandRecord, ConferenceTarget, PaperArtifact, PaperArtifactKind, PaperBuildRecord,
    PaperCitationBinding, PaperRevision,
)


class PaperBuildError(RuntimeError):
    pass


class LatexPaperRenderer:
    def __init__(self, workspace, known_secrets=lambda: ()) -> None:
        self.workspace = workspace
        self.known_secrets = known_secrets

    def render(self, revision: PaperRevision, sources: Dict[str, LiteratureSource],
               figure_sources: Dict[str, Path]) -> Tuple[PaperBuildRecord, List[PaperArtifact]]:
        root = self.workspace.project_root(revision.project_id) / "papers" / revision.paper_id / (
            f"revision-{revision.revision}"
        )
        if root.exists():
            raise PaperBuildError("immutable paper revision output already exists")
        (root / "figures").mkdir(parents=True)
        (root / "tables").mkdir()
        (root / "pages").mkdir()

        generated_ids = [revision.revision_id, revision.research_review_run_id]
        files: List[Tuple[Path, PaperArtifactKind, str, List[str]]] = []
        for figure in revision.content.figures:
            source = figure_sources.get(figure.label)
            if source is None or not source.is_file():
                raise PaperBuildError(f"figure source missing for {figure.label}")
            destination = root / figure.bundled_relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            expected = figure.source_sha256
            actual = self._sha256(destination)
            if expected and expected != actual:
                raise PaperBuildError(f"figure hash mismatch for {figure.label}")
            files.append((destination, PaperArtifactKind.FIGURE, self._media(destination), [
                figure.source_artifact_id or figure.legacy_relative_path or figure.label,
            ]))

        bib = root / "references.bib"
        bib.write_text(self._bibtex(revision.content.citation_bindings, sources), encoding="utf-8")
        files.append((bib, PaperArtifactKind.REFERENCES_BIB, "application/x-bibtex", generated_ids))

        appendix = root / "appendix.tex"
        appendix.write_text(self._appendix_tex(revision), encoding="utf-8")
        files.append((appendix, PaperArtifactKind.APPENDIX, "application/x-tex", generated_ids))

        reproducibility = root / "reproducibility_statement.md"
        reproducibility.write_text(
            "# Reproducibility Statement\n\n" + revision.content.reproducibility_statement.strip() + "\n",
            encoding="utf-8",
        )
        files.append((reproducibility, PaperArtifactKind.REPRODUCIBILITY_STATEMENT, "text/markdown", generated_ids))

        for table in revision.content.tables:
            table_path = root / "tables" / (table.label.replace(":", "-") + ".tex")
            table_path.write_text(self._table_tex(table), encoding="utf-8")
            files.append((table_path, PaperArtifactKind.TABLE, "application/x-tex", table.source_artifact_ids))

        preview = root / "preview.md"
        preview.write_text(self._markdown(revision), encoding="utf-8")
        files.append((preview, PaperArtifactKind.MARKDOWN_PREVIEW, "text/markdown", generated_ids))

        tex = root / "paper.tex"
        tex.write_text(self._paper_tex(revision), encoding="utf-8")
        files.append((tex, PaperArtifactKind.PAPER_TEX, "application/x-tex", generated_ids))

        commands: List[BuildCommandRecord] = []
        pdflatex = self._required_tool("pdflatex")
        bibtex = self._required_tool("bibtex")
        pdftoppm = self._required_tool("pdftoppm")
        pdfinfo = self._required_tool("pdfinfo")
        pdftotext = self._required_tool("pdftotext")

        latex_argv = [
            pdflatex, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
            "-file-line-error", "paper.tex",
        ]
        commands.append(self._run(latex_argv, root, revision.config.build_timeout_seconds))
        if commands[-1].exit_code == 0:
            commands.append(self._run([bibtex, "paper"], root, revision.config.build_timeout_seconds))
        if all(item.exit_code == 0 for item in commands):
            commands.append(self._run(latex_argv, root, revision.config.build_timeout_seconds))
            commands.append(self._run(latex_argv, root, revision.config.build_timeout_seconds))

        log = root / "build.log"
        log.write_text("\n\n".join(
            "ARGV: " + " ".join(item.argv) + "\nEXIT: " + str(item.exit_code)
            + "\nSTDOUT:\n" + item.stdout_tail + "\nSTDERR:\n" + item.stderr_tail
            for item in commands
        ), encoding="utf-8")
        files.append((log, PaperArtifactKind.BUILD_LOG, "text/plain", generated_ids))

        pdf = root / "paper.pdf"
        build_ok = bool(commands) and all(item.exit_code == 0 for item in commands) and pdf.is_file()
        page_count = 0
        visual_notes: List[str] = []
        rendered_paths: List[Path] = []
        if build_ok:
            info = self._run([pdfinfo, str(pdf)], root, 30)
            commands.append(info)
            match = re.search(r"^Pages:\s+(\d+)\s*$", info.stdout_tail, re.MULTILINE)
            page_count = int(match.group(1)) if match else 0
            text_check = self._run([pdftotext, str(pdf), "-"], root, 30)
            commands.append(text_check)
            required = ["Abstract", "Introduction", "References", "Reproducibility Statement"]
            missing = [item for item in required if item not in text_check.stdout_tail]
            if missing:
                visual_notes.append("missing rendered headings: " + ", ".join(missing))
            if "??" in text_check.stdout_tail:
                visual_notes.append("unresolved reference marker in rendered PDF")
            render = self._run([
                pdftoppm, "-png", "-r", "110", str(pdf), str(root / "pages" / "page")
            ], root, revision.config.build_timeout_seconds)
            commands.append(render)
            rendered_paths = sorted((root / "pages").glob("page-*.png"))
            if render.exit_code != 0 or len(rendered_paths) != page_count:
                visual_notes.append("PDF page rendering did not produce one PNG per page")
            # First-pass undefined references are expected before BibTeX. Only the final
            # LaTeX pass is authoritative for resolved citations and layout warnings.
            final_latex_output = next(
                item.stdout_tail for item in reversed(commands)
                if Path(item.argv[0]).stem.lower() == "pdflatex"
            )
            for pattern, note in (
                ("undefined citations", "undefined citations in LaTeX build"),
                ("undefined references", "undefined references in LaTeX build"),
                ("Overfull \\hbox", "overfull horizontal box in LaTeX build"),
                ("Fatal error", "fatal LaTeX error"),
            ):
                if pattern.lower() in final_latex_output.lower():
                    visual_notes.append(note)
        if not build_ok:
            visual_notes.append("LaTeX/BibTeX build failed")
        visual_passed = build_ok and page_count > 0 and not visual_notes

        if pdf.is_file():
            files.append((pdf, PaperArtifactKind.PDF, "application/pdf", generated_ids))
        for rendered in rendered_paths:
            files.append((rendered, PaperArtifactKind.PDF_PAGE_RENDER, "image/png", [revision.revision_id]))

        artifacts = [self._artifact(revision, root, *item) for item in files]
        pdf_artifact = next((item for item in artifacts if item.kind is PaperArtifactKind.PDF), None)
        page_artifacts = [
            item.paper_artifact_id for item in artifacts
            if item.kind is PaperArtifactKind.PDF_PAGE_RENDER
        ]
        return PaperBuildRecord(
            paper_id=revision.paper_id,
            project_id=revision.project_id,
            revision_id=revision.revision_id,
            revision_content_hash=revision.content_hash,
            commands=commands,
            success=visual_passed,
            page_count=page_count,
            paper_artifact_ids=[item.paper_artifact_id for item in artifacts],
            pdf_artifact_id=pdf_artifact.paper_artifact_id if pdf_artifact else None,
            rendered_page_artifact_ids=page_artifacts,
            visual_qa_passed=visual_passed,
            visual_qa_notes=visual_notes,
        ), artifacts

    def _paper_tex(self, revision: PaperRevision) -> str:
        content = revision.content
        target = revision.config.target
        two_column = target in {ConferenceTarget.NEURIPS, ConferenceTarget.ICML}
        venue = {
            ConferenceTarget.NEURIPS: "NeurIPS-style",
            ConferenceTarget.ICML: "ICML-style",
            ConferenceTarget.ICLR: "ICLR-style",
            ConferenceTarget.GENERIC_TOP_CONFERENCE: "Generic top-conference",
        }[target]
        sections = {item.section: item for item in content.sections}
        citation_by_section: Dict[object, List[str]] = {}
        for binding in content.citation_bindings:
            citation_by_section.setdefault(binding.section, []).append(binding.citation_key)
        number_values = {item.binding_id: item.literal for item in content.number_bindings}
        lines = [
            r"\documentclass[10pt]{article}",
            r"\usepackage[letterpaper,margin=0.82in]{geometry}",
            r"\usepackage[T1]{fontenc}", r"\usepackage[utf8]{inputenc}",
            r"\usepackage{microtype}", r"\usepackage{graphicx}", r"\usepackage{booktabs}",
            r"\usepackage{array}", r"\usepackage{xcolor}", r"\usepackage[hidelinks]{hyperref}",
            r"\usepackage[numbers,sort&compress]{natbib}", r"\setlength{\parskip}{3pt}",
            r"\setlength{\parindent}{1em}", r"\sloppy",
            r"\hypersetup{pdfsubject={" + self._tex(venue + " built-in compatible manuscript template") + "}}",
            r"\title{" + self._tex(content.title) + "}",
            r"\author{" + self._tex(", ".join(revision.config.author_names)) + "}",
            r"\date{}", r"\begin{document}",
        ]
        if two_column:
            lines.append(r"\twocolumn")
        lines.extend([
            r"\maketitle", r"\begin{abstract}",
            self._markers(content.abstract, number_values), r"\end{abstract}",
        ])
        for section_name in (
            "introduction", "related_work", "method", "theory", "experimental_setup",
            "results", "analysis", "limitations", "broader_impact", "conclusion",
        ):
            section = next((item for item in content.sections if item.section.value == section_name), None)
            if not section:
                continue
            lines.extend([r"\section{" + self._tex(section.title) + "}"])
            for paragraph in section.paragraphs:
                lines.append(self._markers(paragraph, number_values) + "\n")
            keys = sorted(set(citation_by_section.get(section.section, [])))
            if keys:
                lines.append(r"\cite{" + ",".join(keys) + "}")
            if section_name == "results":
                lines.extend(self._figures_tex(revision))
                lines.extend(self._tables_inputs(revision))
                lines.extend(self._algorithms_tex(revision))
        lines.extend([
            r"\section{Reproducibility Statement}", self._tex(content.reproducibility_statement),
            r"\bibliographystyle{plainnat}", r"\bibliography{references}",
            r"\clearpage", r"\onecolumn" if two_column else "", r"\appendix",
            r"\input{appendix.tex}", r"\end{document}", "",
        ])
        return "\n".join(lines)

    def _appendix_tex(self, revision: PaperRevision) -> str:
        values = {item.binding_id: item.literal for item in revision.content.number_bindings}
        lines = []
        for section in revision.content.appendix_sections:
            lines.append(r"\section{" + self._tex(section.title) + "}")
            lines.extend(self._markers(item, values) for item in section.paragraphs)
        return "\n\n".join(lines) + "\n"

    def _figures_tex(self, revision: PaperRevision) -> List[str]:
        lines = []
        for figure in revision.content.figures:
            path = figure.bundled_relative_path.replace("\\", "/")
            supported = Path(path).suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}
            caption = figure.caption
            if figure.legacy_unverified and "legacy/unverified" not in caption.lower():
                caption = "Legacy/unverified: " + caption
            lines.extend([r"\begin{figure}[t]", r"\centering"])
            if supported:
                lines.append(r"\includegraphics[width=0.94\linewidth]{" + self._tex_path(path) + "}")
            else:
                lines.append(r"\fbox{\parbox{0.88\linewidth}{\centering Verified vector figure bundled at \texttt{" + self._tex(path) + "}.}}")
            lines.extend([
                r"\caption{" + self._tex(caption) + "}",
                r"\label{" + figure.label + "}", r"\end{figure}",
            ])
        return lines

    @staticmethod
    def _tables_inputs(revision: PaperRevision) -> List[str]:
        return [r"\input{tables/" + table.label.replace(":", "-") + ".tex}" for table in revision.content.tables]

    def _algorithms_tex(self, revision: PaperRevision) -> List[str]:
        lines = []
        for algorithm in revision.content.algorithms:
            lines.extend([
                r"\begin{figure}[t]", r"\centering",
                r"\fbox{\begin{minipage}{0.90\linewidth}",
                r"\textbf{" + self._tex(algorithm.caption) + r"}\\",
                r"\begin{enumerate}",
                *[r"\item " + self._tex(step) for step in algorithm.steps],
                r"\end{enumerate}", r"\end{minipage}}",
                r"\caption{" + self._tex(algorithm.caption) + "}",
                r"\label{" + algorithm.label + "}", r"\end{figure}",
            ])
        return lines

    def _table_tex(self, table) -> str:
        columns = "l" * len(table.columns)
        rows = [" & ".join(self._tex(item) for item in table.columns) + r" \\", r"\midrule"]
        rows.extend(" & ".join(self._tex(item) for item in row) + r" \\" for row in table.rows)
        return "\n".join([
            r"\begin{table}[t]", r"\centering", r"\small",
            r"\caption{" + self._tex(table.caption) + "}", r"\label{" + table.label + "}",
            r"\begin{tabular}{" + columns + "}", r"\toprule", *rows, r"\bottomrule",
            r"\end{tabular}", r"\end{table}", "",
        ])

    def _markdown(self, revision: PaperRevision) -> str:
        content = revision.content
        lines = ["# " + content.title, "", "## Abstract", "", content.abstract, ""]
        for section in content.sections:
            lines.extend(["## " + section.title, "", *section.paragraphs, ""])
        lines.extend(["## Reproducibility Statement", "", content.reproducibility_statement, ""])
        if content.citation_bindings:
            lines.extend(["## References", ""])
            lines.extend(
                f"- `{item.citation_key}`: source `{item.source_id}`, locator `{item.locator.model_dump(mode='json')}`"
                for item in content.citation_bindings
            )
        return "\n".join(lines) + "\n"

    def _bibtex(self, bindings: Iterable[PaperCitationBinding],
                sources: Dict[str, LiteratureSource]) -> str:
        entries = []
        for binding in sorted(bindings, key=lambda item: item.citation_key):
            source = sources[binding.source_id]
            fields = {
                "title": source.title,
                "author": " and ".join(source.authors) if source.authors else "Unknown",
                "year": source.publication_year or "n.d.",
                "journal": ", ".join(item.value for item in source.origins) or "Unspecified venue",
            }
            if source.doi:
                fields["doi"] = source.doi
            if source.landing_url:
                fields["url"] = source.landing_url
            locator = binding.locator.model_dump(mode="json", exclude_none=True)
            fields["note"] = "Verified source; locator: " + ", ".join(
                f"{key}={value}" for key, value in locator.items() if value not in (None, [], "")
            )
            body = ",\n".join(
                f"  {key} = {{{self._bib(value)}}}" for key, value in fields.items()
            )
            entries.append(f"@article{{{binding.citation_key},\n{body}\n}}")
        return "\n\n".join(entries) + "\n"

    def _markers(self, value: str, numbers: Dict[str, str]) -> str:
        for binding_id, literal in numbers.items():
            value = value.replace("{{num:" + binding_id + "}}", literal)
        value = re.sub(r"\{\{claim:[^}]+\}\}", "", value)
        return self._tex(value)

    @staticmethod
    def _tex(value: str) -> str:
        replacements = {
            "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
            "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
            "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        }
        return "".join(replacements.get(char, char) for char in value)

    @staticmethod
    def _tex_path(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
            raise PaperBuildError("unsafe figure path for TeX")
        return value

    @staticmethod
    def _bib(value) -> str:
        return str(value).replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ")

    @staticmethod
    def _required_tool(name: str) -> str:
        resolved = shutil.which(name)
        if not resolved:
            raise PaperBuildError(f"required paper build tool is unavailable: {name}")
        return resolved

    def _run(self, argv: List[str], cwd: Path, timeout: int) -> BuildCommandRecord:
        completed = subprocess.run(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, shell=False,
            env=self._child_environment(),
        )
        return BuildCommandRecord(
            argv=argv, exit_code=completed.returncode,
            stdout_tail=completed.stdout[-120_000:], stderr_tail=completed.stderr[-120_000:],
        )

    def _child_environment(self) -> dict:
        import os
        blocked = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"}
        return {
            key: value for key, value in os.environ.items()
            if key.upper() not in blocked and not key.upper().startswith("AUTORESEARCH_V0_2_LLM_API_KEY")
        }

    def _artifact(self, revision, root, path, kind, media_type, generated_from):
        return PaperArtifact(
            paper_id=revision.paper_id, project_id=revision.project_id,
            revision_id=revision.revision_id, kind=kind,
            relative_path=path.relative_to(self.workspace.project_root(revision.project_id)).as_posix(),
            sha256=self._sha256(path), size_bytes=path.stat().st_size, media_type=media_type,
            generated_from_record_ids=list(generated_from),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _media(path: Path) -> str:
        return {
            ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
        }.get(path.suffix.lower(), "application/octet-stream")
