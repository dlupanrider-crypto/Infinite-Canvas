from typing import Any, Callable, Dict


def build_app_info(
    *,
    current_version: str,
    read_update_notes: Callable[[str], Dict[str, Any]],
    github_repo_url: str,
    github_version_url: str,
    github_tree_url: str,
    github_update_notes_url: str,
    modelscope_repo_url: str,
    modelscope_version_url: str,
    modelscope_tree_url: str,
    modelscope_update_notes_url: str,
) -> Dict[str, Any]:
    return {
        "version": current_version,
        "repo_url": github_repo_url,
        "version_url": github_version_url,
        "tree_url": github_tree_url,
        "sources": {
            "github": {
                "label": "GitHub",
                "repo_url": github_repo_url,
                "version_url": github_version_url,
                "tree_url": github_tree_url,
                "update_notes_url": github_update_notes_url,
            },
            "modelscope": {
                "label": "ModelScope",
                "repo_url": modelscope_repo_url,
                "version_url": modelscope_version_url,
                "tree_url": modelscope_tree_url,
                "update_notes_url": modelscope_update_notes_url,
            },
        },
        "update_notes": read_update_notes(current_version),
    }

