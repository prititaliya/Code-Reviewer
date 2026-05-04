import logging
from threading import Thread

from fastapi import FastAPI, Request, HTTPException
from api.CommentReviewBot import Orchestrator, post_an_answer_to_github,run_agent
from ReviewState import CommentReviewBotState
from mangum import Mangum
app = FastAPI()
handler = Mangum(app)
logger = logging.getLogger(__name__)


def process_review_comment(state: CommentReviewBotState) -> None:
    try:
        run_agent(state)
    except Exception:
        logger.exception("Background review bot processing failed")

@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/")
async def github_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        logger.exception("Invalid JSON payload received by webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        action = payload.get("action", "")
        comment = payload.get("comment", {})
        pull_request = payload.get("pull_request", {})
        repository = payload.get("repository", {})
        sender = payload.get("sender", {})

        logger.info(
            "Webhook received action=%s repository=%s comment_present=%s",
            action,
            repository.get("full_name"),
            bool(comment),
        )

        if (action == "created" or action == "edited") and comment:
            if "@review-bot" in comment.get("body", ""):
                logger.info("Review bot mentioned in comment")
                state = CommentReviewBotState(
                    action=action,
                    comment=comment,
                    pull_request=pull_request,
                    repository=repository,
                    sender=sender,
                    answer=None,
                )
                Thread(target=process_review_comment, args=(state,), daemon=True).start()
                return {"message": "Review bot is processing the comment"}

        return {"message": "Webhook received"}

    except Exception:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")
