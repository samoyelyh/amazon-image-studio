"""Private chat projections for the existing generic project/asset APIs."""
from sqlalchemy import select
from app.models.hermes_agent import HermesConversation, HermesMessage
from app.models.content import GeneratedOutput
from app.models.agent_control import AgentRun, AgentJobLink


def agent_project_exists(project_id):
    return select(HermesConversation.id).where(HermesConversation.context_project_id == project_id,
        HermesConversation.controller_type.in_(['langgraph','dsh']), HermesConversation.mode == 'chat').exists()


def agent_output_exists(asset_id):
    return (select(GeneratedOutput.id).join(AgentJobLink, AgentJobLink.job_id == GeneratedOutput.job_id)
        .join(AgentRun, AgentRun.id == AgentJobLink.run_id).join(HermesConversation, HermesConversation.id == AgentRun.conversation_id)
        .where(GeneratedOutput.asset_id == asset_id, HermesConversation.controller_type.in_(['langgraph','dsh']),
               HermesConversation.mode == 'chat').exists())


def agent_attachment_exists(asset_id):
    return select(HermesMessage.id).join(HermesConversation, HermesConversation.id == HermesMessage.conversation_id).where(
        HermesConversation.controller_type.in_(['langgraph','dsh']), HermesConversation.mode == 'chat', HermesMessage.role == 'attachment',
        HermesMessage.metadata_json['asset_id'].as_string() == asset_id).exists()
