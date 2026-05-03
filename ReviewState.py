from pyexpat.errors import messages
from typing import Annotated, List, Any, Optional, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class CommentsReview(TypedDict):
    comments_review: str
    line: int
    file: str



class Summary(TypedDict):
    """
    A TypedDict representing a summary result.

    Attributes:
        summary (str): The summary text for result.
        result (str): The result or outcome associated with the summary.
        result_markdown (str): A markdown-formatted version of the result for better readability.
        code_suggestions (str): Suggestions for code improvement based on the previous comments.
    """
    summary: str
    result: str
    result_markdown: str
    code_suggestions: str

class ReviewState(TypedDict, total=False):
    diff_stats: str
    full_diff: str
    code_comments: list[CommentsReview]
    summary: str
    plan: str
    action: str
    result: str
    markdown_summary: str
    iteration: int
    comments_review: str
    thoughts: str
    questions_to_think_through: str
    context_for_thoughts: str
    messages: Annotated[list[BaseMessage], add_messages]
    API_Change_Flag: bool