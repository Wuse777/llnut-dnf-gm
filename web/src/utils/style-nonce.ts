/** Only trusted application style producers receive the server's document nonce. */
export function applyStyleNonce(style: HTMLStyleElement): void {
  const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce;
  if (nonce && /^[A-Za-z0-9_-]{43}$/.test(nonce)) style.nonce = nonce;
}
