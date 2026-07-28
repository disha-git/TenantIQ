from sqlalchemy.orm import Session
from app.models.log import ChatLog
import json


def log_interaction(
    db: Session,
    query: str,
    intent: str,
    confidence: float,
    entities: list,
    response: str,
    route: str = "llm",
    session_id: str = None,
):
    """
    Saves a single chat interaction to the MySQL database.
    """
    try:
        log_entry = ChatLog(
            user_query=query,
            detected_intent=intent,
            confidence_score=confidence,
            extracted_entities=json.dumps(entities),
            llm_response=response,
            route=route,
            session_id=session_id,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
    except Exception as e:
        print(f"Failed to log interaction to DB: {e}")
        db.rollback()