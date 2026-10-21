// The meal being served right now (local time) — used to pre-select it.
export function currentMeal(date = new Date()) {
  const h = date.getHours();
  if (h < 11) return "breakfast";
  if (h < 16) return "lunch";
  if (h < 19) return "snacks";
  return "dinner";
}
