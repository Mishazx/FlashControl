import datetime

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .machine_auth import enroll_source_allowed, hash_machine_token, new_machine_token
from .models import Agent
from .schemas import AgentEnrollIn, AgentEnrollOut


def _same_computer(agent: Agent, hostname: str, domain: str | None) -> bool:
    return (
        (agent.hostname or "").casefold() == (hostname or "").casefold()
        and (agent.domain or "").casefold() == (domain or "").casefold()
    )


def issue_agent_token(
    request: Request,
    payload: AgentEnrollIn,
    db: Session,
) -> AgentEnrollOut:
    if not enroll_source_allowed(request):
        raise HTTPException(status_code=403, detail="enrollment is not allowed from this network")

    now = datetime.datetime.now(datetime.timezone.utc)
    source = request.client.host if request.client else None
    agent = db.get(Agent, payload.agent_id)
    if agent is not None and agent.token_hash and not _same_computer(
        agent, payload.hostname, payload.domain
    ):
        raise HTTPException(status_code=403, detail="agent identity is bound to another computer")

    token = new_machine_token()
    token_hash = hash_machine_token(token)
    if agent is None:
        agent = Agent(
            id=payload.agent_id,
            hostname=payload.hostname,
            domain=payload.domain,
            agent_version=payload.agent_version,
            current_ips=payload.current_ips,
            queue_size=0,
            selected_route="offline",
            source_ip=source,
            token_hash=token_hash,
            enroll_source_ip=source,
            enrolled_at_utc=now,
            first_seen_at_utc=now,
            last_seen_at_utc=now,
        )
        db.add(agent)
    else:
        agent.hostname = payload.hostname
        agent.domain = payload.domain
        agent.agent_version = payload.agent_version
        agent.current_ips = payload.current_ips
        agent.source_ip = source
        agent.token_hash = token_hash
        agent.enroll_source_ip = source
        agent.enrolled_at_utc = now
        agent.last_seen_at_utc = now
    db.commit()
    return AgentEnrollOut(agent_id=payload.agent_id, machine_token=token)
