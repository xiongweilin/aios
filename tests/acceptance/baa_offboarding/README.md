# BAA employee-offboarding network acceptance

This acceptance target exercises a production-like network boundary without touching real employee,
Odoo, or Keycloak state.

Topology:

~~~text
AIOS OffboardingExecutionEngine (runner process)
  -> BAA gate (BAA-Protocol checkout)
  -> WorldRuntimeBridge over HTTP
  -> World Runtime container
  -> network effect provider
  -> isolated sandbox container

Independent read-back:
BAA gate -> HttpEffectProvider.observe -> sandbox container
~~~

The experiment covers:

- a normal three-effect offboarding episode;
- a real lost-ack condition where the sandbox commits the effect before the Runtime provider times out;
- a transient independent read-back outage;
- a direct Runtime invocation without an authorization.

Hard fixture assertions include:

- normal episode completes with exactly three unique writes;
- lost ACK enters reconciliation and does not duplicate a committed reality effect;
- read-back outage preserves uncertainty and recovery does not duplicate reality writes;
- an un-authorized Runtime request is rejected before reaching the provider.

This target is deliberately synthetic. Passing it does not constitute real Odoo/Keycloak evidence,
production credential-isolation evidence, or a delegation-leverage estimate.
