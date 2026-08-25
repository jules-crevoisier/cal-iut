/** Copie presse-papiers avec repli — `navigator.clipboard` est refusé hors
 * contexte sécurisé (http:// sur un autre poste du réseau local, par ex.). */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    ta.remove();
    if (!ok) window.prompt("Copier ce lien :", text);
    return ok;
  }
}
