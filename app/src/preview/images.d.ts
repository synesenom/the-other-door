// Vite hands an imported image to the preview as its URL.
declare module '*.png' {
  const url: string
  export default url
}

// …and an SVG asked for `?raw` as its text (the pairing QR code, as `pair_phone` answers it).
declare module '*.svg?raw' {
  const text: string
  export default text
}
