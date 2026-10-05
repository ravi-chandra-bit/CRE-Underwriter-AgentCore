// Hard limit: no principal may record a credit decision or send an adverse action notice
// through the agent's gateway, whatever their role. Forbid overrides every permit.
// Credit decisions and ECOA/Reg B notices are made by authorised humans in the LOS itself.
forbid(
  principal,
  action in [
    AgentCore::Action::"los___record_credit_decision",
    AgentCore::Action::"los___send_adverse_action_notice"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
);
