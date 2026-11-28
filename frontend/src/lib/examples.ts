/** Example prompts. Each one is routed to REAL MCP tools by the model; `tools` lists what a capable model is expected to call
 *  (it is a hint shown in the UI, not a guarantee -- the Workspace shows which tools were actually called). */
export const EXAMPLES = [
  { title: "Overdue invoices", prompt: "Show the top overdue invoices with customer names and amounts.", tools: ["db__query"], icon: "database" },
  { title: "Inspect the schema", prompt: "Which tables are in the database and how are they related?", tools: ["db__list_tables", "db__describe_table"], icon: "database" },
  { title: "Search the docs", prompt: "Search the docs for our refund policy and summarise it.", tools: ["knowledge__index_folder", "knowledge__search_knowledge"], icon: "book" },
  { title: "Recent commits", prompt: "Show the recent git commits in this repository.", tools: ["repo__git_log"], icon: "git" },
  { title: "Do the maths", prompt: "Calculate 450000 * 0.18 and explain what GST at 18% means here.", tools: ["utility__calculate"], icon: "calc" },
  { title: "Remember a preference", prompt: "Remember that I prefer amounts in INR lakhs.", tools: ["memory__remember"], icon: "brain" },
];
export const WORKFLOW_PROMPT = EXAMPLES[0].prompt;
