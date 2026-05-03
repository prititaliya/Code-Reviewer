from pathlib import Path
import json
import re
from ReviewState import CommentsReview;
class InputFormatter:
    def difference_stats(self, fileName: str) -> list[str]:
        with open(fileName, 'r') as f:
            input_str = f.read()
        result = "<<DIFF_STATS_START>>\n" + input_str.strip() + "\n<<DIFF_STATS_END>>"
        return result.strip().split('\n')

    def full_code_diff(self, fileName: str) -> list[str]:
        with open(fileName, 'r') as f:
            input_str = f.read()
        result = "<<CODE_DIFF_START>>\n" + input_str.strip() + "\n<<CODE_DIFF_END>>"
        return result.strip().split('\n')
    
    def parse_comments(self, fileName: str) -> list[CommentsReview]:
        with open(fileName, 'r') as f:
            comments_data = json.load(f)
        print("Raw comments data loaded from file:", comments_data)  # Debug print to check raw data
        comments_review_list = []
        if isinstance(comments_data, dict):
            comments = [comments_data]
        elif isinstance(comments_data, list):
            comments = comments_data
        else:
            comments = []
        for comment in comments:
            print("Processing comment:", comment)  # Debug print to check each comment being processed
            # Try to get file/path and line/original_line, fallback to None
            file_path = comment.get("file") or comment.get("path")
            line = comment.get("line") or comment.get("original_line")
            body = comment.get("body") or comment.get("comment")
            comments_review_list.append(CommentsReview(
                comments_review=body,
                line=line if line is not None else -1,
                file=file_path if file_path is not None else ""
            ))
        
        return comments_review_list

