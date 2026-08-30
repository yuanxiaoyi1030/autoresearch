# Purpose: Statically understands arbitrary imported projects without importing or executing their code or notebooks.
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from research_runtime.state import ImportManifest

from .models import (
    LegacyReferenceUse, MaterialKind, ResearchMaterial, VerificationStatus,
)


MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_TEXT_BYTES = 24 * 1024 * 1024
CODE_SUFFIXES = {".py", ".r", ".jl", ".m", ".sh", ".ps1", ".js", ".ts"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock"}
TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".feather", ".arrow"}
ARRAY_SUFFIXES = {".npy", ".npz", ".h5", ".hdf5", ".mat"}
FIGURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".eps"}
PAPER_SUFFIXES = {".pdf", ".tex", ".bib"}

QUESTION_PATTERN = re.compile(
    r"(?i)(?:research\s+question|question|objective|aim|hypothesis|研究问题|研究目标|目标|假设)\s*[:：-]\s*(.+)"
)
CLAIM_PATTERN = re.compile(
    r"(?i)(?:conclusion|finding|we\s+(?:find|show|observe)|result|结论|发现|结果)\s*[:：-]?\s*(.+)"
)
EXPERIMENT_PATTERN = re.compile(
    r"(?i)\b(experiment|trial|train|evaluate|evaluation|simulate|simulation|benchmark|ablation|cross[_-]?validation|实验|训练|评估|仿真)\w*\b"
)
METRIC_PATTERN = re.compile(
    r"(?i)\b(metric|score|accuracy|precision|recall|f1|auc|loss|error|rmse|mae|mse|likelihood|effect[_ -]?size|p[_ -]?value|confidence[_ -]?interval|指标|准确率|损失|误差)\w*\b"
)
DATA_PATTERN = re.compile(
    r"(?i)\b(data|dataset|sample|cohort|schema|feature|label|observation|measurement|数据|样本|特征|标签)\w*\b"
)
RESULT_PATH_PATTERN = re.compile(r"(?i)(result|metric|evaluation|report|summary|output|结果|指标)")
PLOTTING_PATTERN = re.compile(
    r"(?i)(matplotlib|seaborn|plotly|altair|bokeh|ggplot|savefig|subplots?|scatter|heatmap|imshow|histplot|绘图)"
)
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")
NAMED_STYLE = re.compile(
    r"(?i)(?:color|c|palette|fontfamily|fontname|font_family|font)\s*=\s*['\"]([^'\"]+)['\"]"
)
FIGSIZE = re.compile(r"(?i)figsize\s*=\s*\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)")
DPI = re.compile(r"(?i)dpi\s*=\s*([0-9]+)")
LINESTYLE = re.compile(r"(?i)(?:linestyle|ls)\s*=\s*['\"]([^'\"]+)['\"]")
MARKER = re.compile(r"(?i)marker\s*=\s*['\"]([^'\"]+)['\"]")
SAVE_FORMAT = re.compile(r"(?i)savefig\s*\([^)]*?['\"][^'\"]+\.([a-z0-9]+)['\"]")
CAPTION = re.compile(r"(?im)^\s*(figure|fig\.|图)\s*\d*\s*[:：.-]\s*(.+)$")


class InspectionResult(BaseModel):
    summary: str
    research_questions: List[str]
    materials: List[ResearchMaterial]
    dependencies: List[str] = Field(default_factory=list)
    experiments: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    result_summaries: List[str] = Field(default_factory=list)
    claims: List[str] = Field(default_factory=list)
    known_issues: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    visualization: Dict = Field(default_factory=dict)


class StaticProjectInspector:
    """Reads copied snapshot bytes as data; it never imports modules or executes notebook cells."""

    def inspect(self, snapshot_root: Path, manifest: ImportManifest) -> InspectionResult:
        snapshot_root = Path(snapshot_root).resolve(strict=True)
        materials: List[ResearchMaterial] = []
        questions: List[str] = []
        claims: List[str] = []
        results: List[str] = []
        dependencies: Set[str] = set()
        experiments: Set[str] = set()
        metrics: Set[str] = set()
        issues: List[str] = []
        document_paragraphs: List[str] = []
        visualization_sources: List[str] = []
        visual_texts: List[str] = []
        total_text_bytes = 0

        for source in manifest.files:
            path = self._snapshot_file(snapshot_root, source.relative_path)
            suffix = path.suffix.lower()
            text: Optional[str] = None
            code_text = ""
            markdown_text = ""
            if source.size_bytes <= MAX_TEXT_FILE_BYTES and total_text_bytes < MAX_TOTAL_TEXT_BYTES:
                if source.media_type in {
                    "python_source", "code_source", "notebook", "text", "paper_source",
                    "structured_data", "configuration", "figure",
                } or suffix in CODE_SUFFIXES | CONFIG_SUFFIXES | {".md", ".txt", ".rst", ".tex", ".bib", ".svg"}:
                    try:
                        if suffix == ".ipynb":
                            markdown_text, code_text = self._read_notebook(path)
                            text = markdown_text + "\n" + code_text
                        else:
                            text = path.read_text(encoding="utf-8", errors="replace")
                            code_text = text if suffix in CODE_SUFFIXES else ""
                        total_text_bytes += min(source.size_bytes, MAX_TEXT_FILE_BYTES)
                    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                        issues.append(f"Static read failed for {source.relative_path}: {type(exc).__name__}")
            elif source.size_bytes > MAX_TEXT_FILE_BYTES and self._is_text_candidate(suffix, source.media_type):
                issues.append(f"Skipped oversized text file: {source.relative_path}")

            kinds = self._material_kinds(path, source.media_type, text or "", code_text)
            summary_parts: List[str] = []
            if suffix == ".py" and code_text:
                parsed = self._inspect_python(code_text, source.relative_path, issues)
                dependencies.update(parsed["dependencies"])
                experiments.update(parsed["experiments"])
                metrics.update(parsed["metrics"])
                if parsed["functions"]:
                    summary_parts.append("functions: " + ", ".join(parsed["functions"][:8]))
            elif code_text:
                dependencies.update(self._generic_dependencies(code_text))
                experiments.update(self._matched_terms(EXPERIMENT_PATTERN, code_text))
                metrics.update(self._matched_terms(METRIC_PATTERN, code_text))

            if text:
                questions.extend(self._extract_lines(QUESTION_PATTERN, text))
                extracted_claims = self._extract_lines(CLAIM_PATTERN, text)
                claims.extend(extracted_claims)
                if MaterialKind.RESULT in kinds:
                    results.extend(extracted_claims or self._first_meaningful_lines(text, 2))
                if MaterialKind.DOCUMENTATION in kinds or markdown_text:
                    document_paragraphs.extend(self._first_meaningful_lines(markdown_text or text, 3))
                if MaterialKind.PLOTTING_CODE in kinds or suffix == ".svg":
                    visualization_sources.append(source.relative_path)
                    visual_texts.append(text)

            if MaterialKind.FIGURE in kinds:
                visualization_sources.append(source.relative_path)
            if MaterialKind.EXPERIMENT in kinds:
                experiments.add(source.relative_path)
            if MaterialKind.METRIC in kinds:
                metrics.update(self._matched_terms(METRIC_PATTERN, text or path.stem))
            if not summary_parts:
                summary_parts.append("statically classified as " + ", ".join(kind.value for kind in kinds))
            allowed_uses = self._allowed_uses(kinds)
            materials.append(ResearchMaterial(
                relative_path=source.relative_path,
                sha256=source.sha256,
                size_bytes=source.size_bytes,
                media_type=source.media_type,
                kinds=kinds,
                summary="; ".join(summary_parts),
                source_data_available=None,
                allowed_uses=allowed_uses,
            ))

        data_available = any(
            MaterialKind.DATA in item.kinds or MaterialKind.RESULT in item.kinds
            for item in materials
        )
        updated_materials = []
        for item in materials:
            if MaterialKind.FIGURE in item.kinds:
                uses = [
                    LegacyReferenceUse.STYLE_REFERENCE,
                    LegacyReferenceUse.PRELIMINARY_OBSERVATION,
                ]
                if data_available:
                    uses.extend([
                        LegacyReferenceUse.DESIGN_REFERENCE,
                        LegacyReferenceUse.REPRODUCTION_CANDIDATE,
                    ])
                item = item.model_copy(update={
                    "source_data_available": data_available,
                    "allowed_uses": uses,
                })
            updated_materials.append(item)
        materials = updated_materials

        questions = self._unique(questions)
        if not questions:
            questions = [
                "What research question does this imported project address, and which legacy results can be reproduced?"
            ]
            issues.append("No explicit research question was located; the fallback question requires user review.")
        summary = self._summary(document_paragraphs, materials)
        missing = ["All imported claims, results, and figures remain legacy/unverified until reproduced."]
        if not data_available and any(MaterialKind.FIGURE in item.kinds for item in materials):
            missing.append(
                "Figure source data was not located; legacy figures are limited to style or preliminary observation."
            )
        if not any(MaterialKind.CONFIG in item.kinds for item in materials):
            missing.append("No explicit reproducible configuration was located.")
        if not any(MaterialKind.CODE in item.kinds or MaterialKind.NOTEBOOK in item.kinds for item in materials):
            missing.append("No reusable executable source was located.")

        visualization = self._visualization_profile_data(
            visualization_sources, visual_texts, materials,
        )
        return InspectionResult(
            summary=summary,
            research_questions=questions,
            materials=materials,
            dependencies=sorted(dependencies),
            experiments=sorted(experiments),
            metrics=sorted(metrics),
            result_summaries=self._unique(results)[:20],
            claims=self._unique(claims)[:20],
            known_issues=self._unique(issues),
            missing_evidence=missing,
            visualization=visualization,
        )

    @staticmethod
    def _snapshot_file(root: Path, relative_path: str) -> Path:
        supplied = Path(relative_path)
        if supplied.is_absolute() or ".." in supplied.parts:
            raise ValueError("manifest path escapes snapshot")
        path = (root / supplied).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError("manifest path escapes snapshot") from None
        if path.is_symlink() or not path.is_file():
            raise ValueError("snapshot material must be a regular non-symlink file")
        return path

    @staticmethod
    def _is_text_candidate(suffix: str, media_type: str) -> bool:
        return media_type in {"python_source", "code_source", "notebook", "text", "paper_source"} or suffix in CODE_SUFFIXES

    @staticmethod
    def _read_notebook(path: Path) -> Tuple[str, str]:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict) or not isinstance(data.get("cells", []), list):
            raise ValueError("invalid notebook structure")
        markdown: List[str] = []
        code: List[str] = []
        for cell in data.get("cells", []):
            if not isinstance(cell, dict):
                continue
            source = cell.get("source", "")
            value = "".join(source) if isinstance(source, list) else str(source)
            if cell.get("cell_type") == "markdown":
                markdown.append(value)
            elif cell.get("cell_type") == "code":
                code.append(value)
        return "\n".join(markdown), "\n".join(code)

    def _material_kinds(self, path: Path, media_type: str, text: str, code_text: str) -> List[MaterialKind]:
        suffix = path.suffix.lower()
        kinds: Set[MaterialKind] = set()
        if suffix in CODE_SUFFIXES or media_type in {"python_source", "code_source"}:
            kinds.add(MaterialKind.CODE)
        if suffix == ".ipynb" or media_type == "notebook":
            kinds.update({MaterialKind.NOTEBOOK, MaterialKind.CODE})
        if suffix in CONFIG_SUFFIXES or media_type == "configuration":
            kinds.add(MaterialKind.CONFIG)
        if suffix in PAPER_SUFFIXES or media_type in {"paper_pdf", "paper_source"}:
            kinds.add(MaterialKind.PAPER)
        if suffix in FIGURE_SUFFIXES or media_type == "figure":
            kinds.add(MaterialKind.FIGURE)
        if suffix in TABULAR_SUFFIXES | ARRAY_SUFFIXES:
            kinds.add(MaterialKind.RESULT if RESULT_PATH_PATTERN.search(path.as_posix()) else MaterialKind.DATA)
        if media_type == "structured_data" and suffix in {".json", ".yaml", ".yml", ".toml"}:
            if RESULT_PATH_PATTERN.search(path.as_posix()) or CLAIM_PATTERN.search(text):
                kinds.add(MaterialKind.RESULT)
            elif self._looks_like_config(text):
                kinds.add(MaterialKind.CONFIG)
            else:
                kinds.add(MaterialKind.DATA)
        if media_type in {"text", "presentation"} or suffix in {".md", ".txt", ".rst"}:
            kinds.add(MaterialKind.DOCUMENTATION)
            if DATA_PATTERN.search(text):
                kinds.add(MaterialKind.DATA_DESCRIPTION)
        if code_text and EXPERIMENT_PATTERN.search(code_text):
            kinds.add(MaterialKind.EXPERIMENT)
        if text and METRIC_PATTERN.search(text):
            kinds.add(MaterialKind.METRIC)
        if text and (PLOTTING_PATTERN.search(text) or (suffix == ".svg")):
            kinds.add(MaterialKind.PLOTTING_CODE if suffix not in FIGURE_SUFFIXES else MaterialKind.FIGURE)
        if not kinds:
            kinds.add(MaterialKind.BINARY)
        return sorted(kinds, key=lambda item: item.value)

    @staticmethod
    def _looks_like_config(text: str) -> bool:
        return bool(re.search(
            r"(?i)(learning[_-]?rate|batch[_-]?size|seed|epochs?|timeout|model|dataset|optimizer|paths?|parameters?|config)",
            text[:100_000],
        ))

    def _inspect_python(self, source: str, relative_path: str, issues: List[str]) -> Dict[str, List[str]]:
        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as exc:
            issues.append(f"Python syntax could not be parsed for {relative_path}: line {exc.lineno}")
            return {"dependencies": [], "functions": [], "experiments": [], "metrics": []}
        dependencies: Set[str] = set()
        functions: List[str] = []
        call_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                dependencies.add(node.module.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
            elif isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name:
                    call_names.add(name)
        experiments = [name for name in sorted(call_names | set(functions)) if EXPERIMENT_PATTERN.search(name)]
        metrics = [name for name in sorted(call_names | set(functions)) if METRIC_PATTERN.search(name)]
        return {
            "dependencies": sorted(dependencies),
            "functions": sorted(functions),
            "experiments": experiments,
            "metrics": metrics,
        }

    @staticmethod
    def _call_name(node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = StaticProjectInspector._call_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    @staticmethod
    def _generic_dependencies(source: str) -> Set[str]:
        matches = re.findall(r"(?im)^\s*(?:import|from|library|require)\s*\(?\s*([A-Za-z0-9_.-]+)", source)
        return {item.split(".")[0] for item in matches}

    @staticmethod
    def _matched_terms(pattern: re.Pattern, text: str) -> Set[str]:
        return {match.group(0) for match in pattern.finditer(text[:500_000])}

    @staticmethod
    def _extract_lines(pattern: re.Pattern, text: str) -> List[str]:
        values = []
        for line in text.splitlines():
            match = pattern.search(line.strip())
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" #*\t")
                if 4 <= len(value) <= 500:
                    values.append(value)
        return values

    @staticmethod
    def _first_meaningful_lines(text: str, limit: int) -> List[str]:
        values = []
        for line in text.splitlines():
            value = re.sub(r"\s+", " ", line).strip(" #*\t")
            if len(value) >= 8 and not value.startswith(("```", "---", "<svg")):
                values.append(value[:500])
            if len(values) >= limit:
                break
        return values

    @staticmethod
    def _allowed_uses(kinds: Iterable[MaterialKind]) -> List[LegacyReferenceUse]:
        values = {LegacyReferenceUse.DESIGN_REFERENCE}
        kinds = set(kinds)
        if MaterialKind.FIGURE in kinds:
            values.update({
                LegacyReferenceUse.STYLE_REFERENCE,
                LegacyReferenceUse.PRELIMINARY_OBSERVATION,
            })
        if kinds & {MaterialKind.CODE, MaterialKind.NOTEBOOK, MaterialKind.CONFIG, MaterialKind.RESULT}:
            values.add(LegacyReferenceUse.REPRODUCTION_CANDIDATE)
        return sorted(values, key=lambda item: item.value)

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        output = []
        seen = set()
        for value in values:
            normalized = re.sub(r"\s+", " ", str(value)).strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                output.append(normalized)
        return output

    @staticmethod
    def _summary(paragraphs: List[str], materials: List[ResearchMaterial]) -> str:
        if paragraphs:
            return " ".join(StaticProjectInspector._unique(paragraphs)[:3])[:1500]
        counts: Dict[str, int] = {}
        for material in materials:
            for kind in material.kinds:
                counts[kind.value] = counts.get(kind.value, 0) + 1
        inventory = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        return f"Static snapshot inventory for a legacy project: {inventory or 'no recognized materials'}."

    def _visualization_profile_data(
        self, source_paths: List[str], texts: List[str], materials: List[ResearchMaterial],
    ) -> Dict:
        combined = "\n".join(texts)[:4_000_000]
        colors = set(HEX_COLOR.findall(combined))
        fonts = set()
        for match in NAMED_STYLE.finditer(combined):
            value = match.group(1).strip()
            if "font" in match.group(0).casefold():
                fonts.add(value)
            elif re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{1,30}", value):
                colors.add(value)
        figure_sizes = [[float(match.group(1)), float(match.group(2))] for match in FIGSIZE.finditer(combined)]
        dpi_values = [int(match.group(1)) for match in DPI.finditer(combined)]
        line_styles = [match.group(1) for match in LINESTYLE.finditer(combined)]
        markers = [match.group(1) for match in MARKER.finditer(combined)]
        formats = {match.group(1).lower() for match in SAVE_FORMAT.finditer(combined)}
        formats.update(
            Path(item.relative_path).suffix.lower().lstrip(".")
            for item in materials if MaterialKind.FIGURE in item.kinds
        )
        layouts = []
        for value in ("subplots", "tight_layout", "constrained_layout", "gridspec", "facet"):
            if re.search(rf"(?i)\b{re.escape(value)}\b", combined):
                layouts.append(value)
        caption_match = CAPTION.search(combined)
        notes = []
        if source_paths:
            notes.append("Extracted statically from legacy plotting source and/or figure files.")
        if source_paths and not texts:
            notes.append("No plotting source was readable; profile is limited to file-format inventory.")
        return {
            "source_paths": self._unique(source_paths),
            "colors": sorted(colors),
            "fonts": sorted(fonts),
            "figure_sizes_inches": self._unique_lists(figure_sizes),
            "layouts": layouts,
            "line_styles": self._unique(line_styles),
            "markers": self._unique(markers),
            "dpi_values": sorted(set(dpi_values)),
            "output_formats": sorted(value for value in formats if value),
            "caption_style": caption_match.group(0)[:300] if caption_match else None,
            "extraction_notes": notes,
        }

    @staticmethod
    def _unique_lists(values: List[List[float]]) -> List[List[float]]:
        output = []
        seen = set()
        for value in values:
            key = tuple(value)
            if key not in seen:
                seen.add(key)
                output.append(value)
        return output
