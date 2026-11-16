/** The pages of one document, one under the other, as the prepared materials and the style previews show them. */
export function PageStack({ urls, label }: { urls: string[]; label: string }) {
  return (
    <div className="pages-stack">
      {urls.map((url, i) => (
        <img key={url} className="paper" src={url} alt={`${label}, page ${i + 1}`} />
      ))}
    </div>
  )
}
