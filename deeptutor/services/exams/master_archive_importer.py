"""Importer service for Sri Lanka ICT Complete AL & OL Lessons & Quizzes Master Archive.

Populates SQLite ``paper_bank`` catalog with:
- 84 A/L (Grade 13) and O/L (Grade 11) Past Papers in English & Sinhala (P1 & P2)
- 30 Daily Quizzes (2027 series)
- 9 Modular Topic Papers
- Diagram assets, KaTeX math formulas, structured sub-questions, marking schemes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import shutil
import time
from typing import Any, Dict, List, Optional

from deeptutor.services.exams.bank_store import BankStore
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_DEFAULT_ARCHIVE_PATH = (
    Path(__file__).resolve().parents[3]
    / "ictfromabc"
    / "Sri_Lanka_ICT_Complete_AL_OL_Lessons_and_Quizzes_Master_Archive"
)


def get_paper_bank_assets_dir() -> Path:
    """Canonical storage directory for Paper Bank diagram assets."""
    dest = get_path_service().user_dir / "workspace" / "paper_bank_assets"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _generate_title(folder_name: str, questions: List[Dict[str, Any]]) -> str:
    """Derive a human-readable title from folder name and question metadata."""
    name = folder_name.lower()
    meta = questions[0].get("metadata", {}) if questions else {}

    if name.startswith("ict-quiz-"):
        quiz_num = meta.get("quiz_number") or (
            re.search(r"q(\d+)", name).group(1) if re.search(r"q(\d+)", name) else ""
        )
        topic = meta.get("topic", "")
        return f"Daily Quiz {quiz_num}: {topic}" if topic else f"Daily Quiz {quiz_num}"

    if name.startswith("ict-topic-"):
        num_m = re.search(r"topic-(\d+)", name)
        num = num_m.group(1) if num_m else ""
        raw_topic = (
            name.split(f"topic-{num}-")[-1].replace("-", " ").title()
            if num
            else name.replace("-", " ").title()
        )
        return f"Topic {num}: {raw_topic}"

    # Past paper e.g. ict-2023-g13-si-p1
    year = meta.get("year") or (
        int(re.search(r"\b(20\d{2})\b", name).group(1))
        if re.search(r"\b(20\d{2})\b", name)
        else 2023
    )
    grade = meta.get("grade") or (11 if "-g11-" in name else 13)
    medium = "Sinhala" if "-si-" in name or meta.get("medium") == "sinhala" else "English"
    level = "O/L" if grade == 11 else "A/L"
    paper_no = "Paper I (MCQ)" if "-p1" in name else "Paper II (Structured/Essay)"
    return f"G.C.E. ({level}) {year} ICT {paper_no} ({medium})"


async def import_master_archive(
    archive_path: Optional[str | Path] = None,
    *,
    copy_assets: bool = True,
) -> Dict[str, Any]:
    """Imports all 123 modules from the master archive into the paper_bank catalog."""
    src = Path(archive_path) if archive_path else _DEFAULT_ARCHIVE_PATH
    if not src.is_dir():
        return {"success": False, "error": f"Archive directory not found: {src}"}

    assets_root = get_paper_bank_assets_dir()
    folders = sorted([d for d in src.iterdir() if d.is_dir() and (d / "paper.json").exists()])
    imported_count = 0
    total_questions = 0
    total_diagrams = 0
    errors: List[str] = []

    for folder in folders:
        try:
            with open(folder / "paper.json", "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            if not isinstance(raw_data, list) or not raw_data:
                continue

            folder_name = folder.name
            first_meta = raw_data[0].get("metadata", {})

            # 1. Classify subject, grade, year, medium, paper_no, paper_type
            if folder_name.startswith("ict-quiz-"):
                subject = "ict-quiz"
                grade = int(first_meta.get("grade") or 13)
                year = int(first_meta.get("year") or 2027)
                medium = "english"
                paper_no = 1
                paper_type = "mcq"
                group_key = folder_name
                row_id = folder_name
                duration = 1800  # 30 mins
            elif folder_name.startswith("ict-topic-"):
                subject = "ict-topic"
                grade = int(first_meta.get("grade") or 13)
                year = int(first_meta.get("year") or 2025)
                medium = "english"
                paper_no = 1
                paper_type = "mcq"
                group_key = folder_name
                row_id = folder_name
                duration = 3600  # 1 hour
            else:
                grade = 11 if "-g11-" in folder_name else 13
                subject = "ict-ol" if grade == 11 else "ict"
                y_match = re.search(r"\b(20\d{2})\b", folder_name)
                year = int(first_meta.get("year") or (y_match.group(1) if y_match else 2023))
                medium = (
                    "sinhala"
                    if "-si-" in folder_name or first_meta.get("medium") == "sinhala"
                    else "english"
                )
                paper_no = 2 if "-p2" in folder_name else 1
                paper_type = "structured" if paper_no == 2 else "mcq"

                # group_key pairs Paper 1 + Paper 2 together
                base_group = f"{subject}-{year}-g{grade}"
                if medium != "english":
                    base_group += f"-{medium[:2]}"
                group_key = base_group
                row_id = f"{group_key}-p{paper_no}"
                duration = 7200 if paper_no == 1 else 10800

            # 2. Copy image assets if present
            img_dir = folder / "images"
            if copy_assets and img_dir.is_dir():
                target_img_dir = assets_root / row_id / "images"
                target_img_dir.mkdir(parents=True, exist_ok=True)
                for img_file in img_dir.glob("*"):
                    if img_file.is_file():
                        shutil.copy2(img_file, target_img_dir / img_file.name)
                        total_diagrams += 1

            # 3. Process questions and format
            normalized_questions: List[Dict[str, Any]] = []
            scheme_answers: Dict[str, str] = {}
            topic_tags: set[str] = set()

            for i, q in enumerate(raw_data, start=1):
                q_num = int(q.get("number") or i)
                stem = str(q.get("stem") or q.get("text") or "").strip()
                ref_ans = str(q.get("reference_answer") or "").strip()
                if ref_ans:
                    scheme_answers[str(q_num)] = ref_ans

                meta = q.get("metadata") or {}
                if meta.get("topic"):
                    topic_tags.add(str(meta["topic"]))

                # Normalize diagrams
                diagrams = q.get("diagrams") or []
                if not diagrams and q.get("images"):
                    for idx, img in enumerate(q["images"]):
                        diagrams.append(
                            {
                                "id": f"d_{q_num}_{idx}",
                                "src": f"images/{Path(str(img)).name}",
                                "alt": f"Diagram for Question {q_num}",
                                "caption": "",
                            }
                        )

                # Ensure image paths are relative to paper assets
                clean_diagrams = []
                for d in diagrams:
                    src_val = str(d.get("src") or "")
                    fname = Path(src_val).name
                    clean_diagrams.append(
                        {
                            "id": str(d.get("id") or f"d_{q_num}"),
                            "src": f"images/{fname}",
                            "alt": str(d.get("alt") or f"Diagram for Question {q_num}"),
                            "caption": str(d.get("caption") or ""),
                        }
                    )

                normalized_questions.append(
                    {
                        "id": str(q.get("id") or f"{row_id}-q{q_num}"),
                        "number": q_num,
                        "question_type": str(
                            q.get("question_type") or ("choice" if paper_no == 1 else "structured")
                        ),
                        "text": stem,
                        "stem": stem,
                        "options": q.get("options"),
                        "marks": float(q.get("marks") or 1.0),
                        "reference_answer": ref_ans or None,
                        "explanation": q.get("explanation"),
                        "section": str(
                            q.get("section") or ("mcq" if paper_no == 1 else "structured")
                        ),
                        "section_number": q_num,
                        "diagrams": clean_diagrams,
                        "sub_questions": q.get("sub_questions") or [],
                        "metadata": meta,
                    }
                )

            title = _generate_title(folder_name, raw_data)
            mcq_count = sum(1 for q in normalized_questions if q["question_type"] == "choice")
            essay_count = len(normalized_questions) - mcq_count
            total_marks = sum(float(q["marks"]) for q in normalized_questions)

            paper_payload = {
                "exam_id": row_id,
                "title": title,
                "source_filename": f"{folder.name}/paper.json",
                "status": "created",
                "total_marks": total_marks,
                "mcq_duration_seconds": duration,
                "essay_duration_seconds": duration if paper_no == 2 else None,
                "question_count": len(normalized_questions),
                "mcq_count": mcq_count,
                "essay_count": essay_count,
                "questions": normalized_questions,
            }

            row = {
                "id": row_id,
                "group_key": group_key,
                "paper_no": paper_no,
                "grade": grade,
                "subject": subject,
                "year": year,
                "medium": medium,
                "paper_type": paper_type,
                "title": title,
                "source_filename": f"{folder.name}/paper.json",
                "file_hash": f"master-archive-{folder_name}",
                "question_count": len(normalized_questions),
                "mcq_count": mcq_count,
                "essay_count": essay_count,
                "total_marks": total_marks,
                "default_duration_seconds": duration,
                "paper_json": paper_payload,
                "scheme_answers": scheme_answers,
                "topic_tags": sorted(topic_tags),
                "created_at": time.time(),
            }

            await BankStore.upsert_paper(row)
            imported_count += 1
            total_questions += len(normalized_questions)

        except Exception as exc:
            logger.exception("Failed to import %s: %s", folder.name, exc)
            errors.append(f"{folder.name}: {exc}")

    return {
        "success": True,
        "imported_papers": imported_count,
        "total_questions": total_questions,
        "total_diagrams_copied": total_diagrams,
        "errors": errors,
    }
