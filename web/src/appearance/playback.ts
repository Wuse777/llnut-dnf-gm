/** One visible appearance animation across cached routes and open panels. */
let owner: { identity: symbol; revoke: () => void } | undefined;

export function acquirePlayback(revoke: () => void): () => void {
  const identity = Symbol('appearance-playback');
  const previous = owner;
  owner = { identity, revoke };
  previous?.revoke();
  return () => { if (owner?.identity === identity) owner = undefined; };
}
