def build_proactive_refusal(project_files: list[str]) -> str:
    """
    Build a standardized refusal response listing the available files
    to guide the user back to the scope of the project.
    """
    base_msg = "I could not find enough information in the uploaded sources for this project to answer that confidently."
    
    if not project_files:
        return f"""{base_msg}

There are currently no documents uploaded to this project. Please upload documents first.

What was checked:
- Relevant project document chunks
- Recent chat context"""

    file_list_str = "\n".join(f"- {f}" for f in sorted(project_files))
    
    return f"""{base_msg}

The documents currently uploaded in this project are:
{file_list_str}

Please ask questions related to the content of these documents.

What was checked:
- Relevant project document chunks
- Recent chat context"""
