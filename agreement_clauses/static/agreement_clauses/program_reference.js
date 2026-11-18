(() => {
  "use strict";
  const program = document.querySelector('[data-need-editor] [name="program"]');
  const catalog = document.getElementById("market-catalog");
  const output = document.querySelector("[data-program-clause-reference]");
  if (!program || !catalog || !output) return;
  const choices = new Map(JSON.parse(catalog.textContent).programs.map(row => [String(row.id), row.clauses]));
  const update = () => {
    output.textContent = choices.get(program.value)?.join("، ") || "—";
  };
  program.addEventListener("change", update);
  update();
})();
