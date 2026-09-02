class ML4GWAgentError(Exception):
    """Base class for expected ML4GW Agent failures."""


class RegistryError(ML4GWAgentError):
    """Raised when skill registration or lookup fails."""


class PlanningError(ML4GWAgentError):
    """Raised when a prompt cannot be converted to a valid plan."""


class PolicyError(ML4GWAgentError):
    """Raised when a plan violates an execution policy."""


class AdapterError(ML4GWAgentError):
    """Raised when a deterministic adapter cannot execute its skill."""


class AdapterUnavailableError(AdapterError):
    """Raised when a requested real adapter is not available."""


class ValidationError(ML4GWAgentError):
    """Raised when skill inputs or outputs fail validation."""
