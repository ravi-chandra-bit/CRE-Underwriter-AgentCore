// Calculation, label mapping and filing a draft memo for review: underwriters and credit
// analysts only. Viewers can read but cannot run the underwriting workflow.
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"los___map_t12_label",
    AgentCore::Action::"uwcalc___compute_cre_metrics",
    AgentCore::Action::"uwcalc___compute_farm_cash_flow_stress",
    AgentCore::Action::"uwcalc___check_credit_policy",
    AgentCore::Action::"los___submit_memo_for_analyst_review"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
) when {
  principal.hasTag("lending_role") &&
  (principal.getTag("lending_role") == "underwriter" ||
   principal.getTag("lending_role") == "credit_analyst") &&
  principal.hasTag("portfolio") &&
  context.input.portfolio == principal.getTag("portfolio")
};
