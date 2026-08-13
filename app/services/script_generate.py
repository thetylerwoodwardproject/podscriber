from app.db import SessionLocal
from app.models import GeneratedScript, Job
from app.services import script_style, settings_store
from app.services.llm.factory import get_llm_provider


def run_script_generation(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        script = db.get(GeneratedScript, job.generated_script_id) if job.generated_script_id else None
        if script is None:
            job.status = "error"
            job.error_message = "Script not found."
            db.commit()
            return

        job.status = "running"
        db.commit()

        llm = get_llm_provider(db)
        excerpts = script_style.style_excerpts(db)
        custom_instructions = settings_store.get(db, "generator_custom_instructions")
        result = llm.generate_script(script.topic, script.research_text, excerpts, custom_instructions)

        script.outline = result.outline
        script.script_text = result.script
        script.llm_provider = type(llm).__name__
        job.status = "done"
        db.commit()
    finally:
        db.close()
