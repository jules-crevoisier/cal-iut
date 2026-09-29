/**
 * Un écran qui plante n'emporte plus toute la page (audit du 29/09/2026,
 * P1-13). Avant, une exception de rendu (comme `park.items` indéfini dans
 * `APlacerView`) donnait une page blanche, navigation comprise.
 *
 * Posée autour du contenu principal (`App.tsx`) : la barre latérale reste
 * utilisable pour changer d'écran. `cle` (l'onglet actif) efface l'erreur
 * quand on change d'écran — sinon le message resterait affiché partout.
 * Une seconde, sans `cle`, entoure toute l'application (`main.tsx`) : dernier
 * filet si c'est la navigation elle-même qui plante.
 *
 * Forcément une classe : React n'offre pas d'équivalent en hook.
 */
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

import "./ErrorBoundary.css";

interface Props {
  children: ReactNode;
  /** Change → l'erreur est oubliée et le contenu retenté. */
  cle?: string;
}

interface State {
  erreur: Error | null;
  pile: string;
  cle?: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { erreur: null, pile: "", cle: this.props.cle };

  static getDerivedStateFromError(erreur: Error): Partial<State> {
    return { erreur };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.cle !== state.cle) return { erreur: null, pile: "", cle: props.cle };
    return null;
  }

  componentDidCatch(erreur: Error, info: ErrorInfo): void {
    this.setState({ pile: info.componentStack ?? "" });
    console.error("Écran en erreur :", erreur, info.componentStack);
  }

  render() {
    const { erreur, pile } = this.state;
    if (!erreur) return this.props.children;
    return (
      <div className="panel erreur-ecran" role="alert">
        <span className="erreur-ecran-marque" aria-hidden="true">
          <TriangleAlert size={18} />
        </span>
        <h2>Cet écran a rencontré une erreur</h2>
        <p>
          Rien n'a été modifié. Rechargez la page ; si l'erreur revient, ouvrez un autre écran et signalez-la avec le
          détail ci-dessous.
        </p>
        <div className="erreur-ecran-actions">
          <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
            Recharger
          </button>
        </div>
        <details>
          <summary>Détail technique</summary>
          <pre>
            {erreur.name}: {erreur.message}
            {pile}
          </pre>
        </details>
      </div>
    );
  }
}
