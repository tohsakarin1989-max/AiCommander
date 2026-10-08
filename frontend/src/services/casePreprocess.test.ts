import { describe, expect, it } from 'vitest'
import { profileStatusLabel } from './casePreprocess'

describe('versioned preprocessing presentation', () => {
  it('distinguishes fresh, changed, missing and unread status', () => {
    expect(profileStatusLabel('ready')).toBe('当前画像可用')
    expect(profileStatusLabel('updating')).toContain('待更新')
    expect(profileStatusLabel('unavailable')).toBe('尚无可用画像')
    expect(profileStatusLabel()).toBe('状态待读取')
    expect(profileStatusLabel('legacy')).not.toContain('已预处理')
  })
})
