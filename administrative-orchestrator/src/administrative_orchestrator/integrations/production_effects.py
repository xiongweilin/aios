from __future__ import annotations

from .communication_effects import (
    AdministrativeCommunicationEffectConnection,
    AdministrativeCommunicationEffectConnector,
    FeishuCommunicationVerifier,
)
from .effect_common import (
    ConnectorConfigurationError,
    ConnectorResult,
    ConnectorStatus,
)
from .effect_common import _ApplicationRejected as _ApplicationRejected
from .effect_common import _TransportUnknown as _TransportUnknown
from .effect_common import _unavailable_result as _unavailable_result
from .effect_common import _unknown_result as _unknown_result
from .effect_common import _validate_base_url as _validate_base_url
from .keycloak_effects import (
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakIdentityVerifier,
    KeycloakSessionRevokeConnector,
    KeycloakSessionVerifier,
)
from .odoo_effects import (
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
    OdooEmployeeVerifier,
)
from .odoo_effects import OdooFinancialEffectConnector as OdooFinancialEffectConnector
from .odoo_effects import OdooFinancialVerifier as OdooFinancialVerifier
from .odoo_effects import _many2one_id as _many2one_id
from .odoo_effects import _odoo_numeric_ref as _odoo_numeric_ref
from .odoo_effects import _required_odoo_numeric_ref as _required_odoo_numeric_ref

# Compatibility import surface. Provider-specific implementations live in the
# bounded modules above; existing callers may continue importing from here.

__all__ = [
    "AdministrativeCommunicationEffectConnection",
    "AdministrativeCommunicationEffectConnector",
    "FeishuCommunicationVerifier",
    "ConnectorConfigurationError",
    "ConnectorResult",
    "ConnectorStatus",
    "KeycloakEffectConnection",
    "KeycloakIdentityDisableConnector",
    "KeycloakIdentityDisableVerifier",
    "KeycloakIdentityEffectConnector",
    "KeycloakIdentityVerifier",
    "KeycloakSessionRevokeConnector",
    "KeycloakSessionVerifier",
    "OdooEffectConnection",
    "OdooEmployeeDeactivateConnector",
    "OdooEmployeeDeactivateVerifier",
    "OdooEmployeeEffectConnector",
    "OdooEmployeeVerifier",
]
