// Read and analysis tools: any lending role, only for the portfolio the user is entitled to.
// `portfolio` and `lending_role` are JWT claims added by the Cognito pre-token trigger and
// surface as principal tags. The LOS Lambda separately checks the deal belongs to that portfolio.
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"los___get_deal_package",
    AgentCore::Action::"los___extract_document",
    AgentCore::Action::"uwcalc___get_evidence",
    AgentCore::Action::"uwcalc___verify_memo_citations"
  ],
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
) when {
  principal.hasTag("lending_role") &&
  principal.hasTag("portfolio") &&
  context.input.portfolio == principal.getTag("portfolio")
};
