import logging
import threading

from fastapi import FastAPI, Request, HTTPException
from api.CommentReviewBot import Orchestrator, post_an_answer_to_github,run_agent
from ReviewState import CommentReviewBotState
from mangum import Mangum
app = FastAPI()
handler = Mangum(app)
logger = logging.getLogger(__name__)


def _process_review_comment(state: CommentReviewBotState) -> None:
    try:
        run_agent(state)
    except Exception:
        logger.exception("Background webhook processing failed")


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/")
async def github_webhook(request: Request):
    print("Received a webhook request from GitHub")
    try:
        payload = await request.json()
    except Exception:
        logger.exception("Invalid JSON payload received by webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        action = payload.get("action", "")
        comment = payload.get("comment") or {}
        issue = payload.get("issue") or {}
        pull_request = issue.get("pull_request") or payload.get("pull_request") or {}
        repository = payload.get("repository") or {}
        sender = payload.get("sender") or {}
        number = issue.get("number") or pull_request.get("number")

        logger.info(
            "Webhook received action=%s repository=%s comment_present=%s",
            action,
            repository.get("full_name"),
            bool(comment),
        )

        if action not in {"created", "edited"}:
            return {"message": f"Ignored action: {action}"}

        if "@review-bot" not in (comment.get("body") or ""):
            return {"message": "Ignored: bot not mentioned"}

        if not pull_request:
            return {"message": "Ignored: not a PR comment"}

        logger.info("Review bot mentioned in comment")
        state = CommentReviewBotState(
            action=action,
            comment=comment,
            issue=issue,
            pull_request=pull_request,
            repository=repository,
            sender=sender,
            number=number,
            answer=None,
        )
        threading.Thread(target=_process_review_comment, args=(state,), daemon=True).start()
        return {"message": "Review bot accepted the comment"}

    except Exception:
        logger.exception("Webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")
