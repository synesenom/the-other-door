import { describe, expect, it } from 'vitest'
import { sharedFrom } from './share'

describe('sharedFrom', () => {
  it('takes the shared url', () => {
    expect(sharedFrom('?url=https%3A%2F%2Fjobs.example.com%2F1&title=Job')).toEqual({ url: 'https://jobs.example.com/1' })
  })
  it('finds the link inside the text, as many apps send it; the first one wins', () => {
    expect(sharedFrom('?text=' + encodeURIComponent('Look at this job https://www.linkedin.com/jobs/view/42/ and https://b.example'))).toEqual({
      url: 'https://www.linkedin.com/jobs/view/42/',
    })
  })
  it('without a link the text is the ad', () => {
    expect(sharedFrom('?text=' + encodeURIComponent('Controller at Acme, Copenhagen. You own the close.'))).toEqual({
      text: 'Controller at Acme, Copenhagen. You own the close.',
    })
  })
  it('nothing shared is null', () => {
    expect(sharedFrom('')).toBeNull()
    expect(sharedFrom('?title=x')).toBeNull()
  })
  it('a link that is not http(s) is not taken', () => {
    expect(sharedFrom('?url=javascript%3Aalert(1)')).toBeNull()
  })
})
