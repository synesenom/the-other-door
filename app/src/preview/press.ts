// A scene that needs an action to reach its state (`Scene.press`): the preview presses the named buttons (by their name: the
// aria-label, else the text) in order,
// each once it is on the page. Development only, like the rest of src/preview/.
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export async function pressInOrder(names: string[], root: ParentNode = document, tries = 100): Promise<void> {
  for (const name of names) {
    for (let i = 0; i < tries; i++) {
      const button = [...root.querySelectorAll('button')].find((b) => (b.getAttribute('aria-label') ?? b.textContent?.trim()) === name && !b.disabled)
      if (button) {
        button.click()
        break
      }
      await sleep(50)
    }
  }
}
