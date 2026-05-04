from fastapi import FastAPI, Request, HTTPException
from api.CommentReviewBot import Orchestrator, post_an_answer_to_github,run_agent
from ReviewState import CommentReviewBotState
from mangum import Mangum
app = FastAPI()
handler = Mangum(app)
@app.get("/")
def read_root():
    return {"Hello": "World1"}


@app.post("/")
async def github_webhook(request: Request):
    try:
       payload = await request.json()
       action = payload.get("action", "")
       comment = payload.get("comment", {})
       pull_request = payload.get("pull_request", {})
       repository = payload.get("repository", {})
       sender = payload.get("sender", {})
       if (action == "created" or action == "edited")  and comment:
          if "@review-bot" in comment.get("body", ""):
                print("Review bot mentioned in comment")
                state = CommentReviewBotState(
                    action=action,
                    comment=comment,
                    pull_request=pull_request,
                    repository=repository,
                    sender=sender,
                    answer=None
                )
                run_agent(state)
                return {"message": "Review bot is processing the comment"}
          
    except Exception:
      raise HTTPException(status_code=400, detail="Invalid JSON")
    # print(payload)
    # return {"message": "Webhook received"}
