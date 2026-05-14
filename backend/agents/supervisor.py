"""Supervisor agent for monitoring AgentFlow workflow completion."""

from __future__ import annotations

from backend.graph.state import AgentState


class SupervisorAgent:
    """Decide the next workflow step and detect completion or errors."""

    def inspect(self, state: AgentState) -> AgentState:
        """Return an updated state with the next agent or completion status."""

        try:
            if state.get("status") == "error":
                return state

            next_agent = self.next_agent(state)
            return {
                **state,
                "current_agent": next_agent,
                "status": "completed" if next_agent == "end" else "running",
                "error": None,
            }
        except Exception as exc:
            return {
                **state,
                "current_agent": "supervisor",
                "status": "error",
                "error": str(exc),
            }

    def next_agent(self, state: AgentState) -> str:
        """Return the next planned agent that has not completed yet."""

        completed = set(state.get("completed_agents", []))
        for agent in state.get("execution_order", []):
            if agent not in completed:
                return agent
        return "end"
