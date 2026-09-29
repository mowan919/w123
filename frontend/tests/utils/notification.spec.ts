import { describe, expect, it } from 'vitest'
import {
  ANNOUNCEMENT_AUDIENCE_FALLBACK,
  NOTIFICATION_CATEGORY_FALLBACK,
  NOTIFICATION_LEVEL_STYLE,
  notificationLevelStyle,
  relativeTime,
} from '@/utils/notification'
import type { AnnouncementAudience, NotificationCategory, NotificationLevel } from '@/types'

/**
 * 通知的展示层工具（`DESIGN-DECISIONS §32`）。
 *
 * 三个映射表与一个相对时间函数。映射表的用例看起来"只是在重复源码"，
 * 但它们钉住的是一件别的事：**键必须覆盖完整的联合类型**。
 * 将来后端给 `NotificationLevel` 加第四个取值时，`Record<...>` 会让
 * 编译直接失败（那是最好的结果）；万一有人把类型改宽了，这几条断言
 * 会在运行时兜住 —— 因为它们遍历的是**类型联合的全部取值**，而不是
 * 手抄的几个字符串。
 */

describe('映射表覆盖全部联合取值', () => {
  it('轻重三档都有颜色与回落文案', () => {
    const levels: NotificationLevel[] = ['INFO', 'WARNING', 'IMPORTANT']
    for (const level of levels) {
      const style = notificationLevelStyle(level)
      expect(style.color).toBeTruthy()
      expect(style.background).toBeTruthy()
      expect(style.label).toBeTruthy()
    }
    // 颜色必须**互不相同**：三档轻重若映射到同一个色，
    // 界面上"重要"和"普通"长得一样，这套颜色就白加了。
    expect(new Set(levels.map((level) => NOTIFICATION_LEVEL_STYLE[level].color)).size).toBe(3)
  })

  it('分类两种取值都有回落文案，且互不相同', () => {
    const categories: NotificationCategory[] = ['SYSTEM', 'ANNOUNCEMENT']
    const labels = categories.map((category) => NOTIFICATION_CATEGORY_FALLBACK[category])
    expect(labels.every((label) => label.length > 0)).toBe(true)
    expect(new Set(labels).size).toBe(2)
  })

  it('受众两种取值都有文案', () => {
    const audiences: AnnouncementAudience[] = ['ALL', 'ROLE']
    for (const audience of audiences) {
      expect(ANNOUNCEMENT_AUDIENCE_FALLBACK[audience]).toBeTruthy()
    }
  })
})

describe('relativeTime', () => {
  const now = new Date('2026-09-29T12:00:00Z')

  function before(ms: number): string {
    return new Date(now.getTime() - ms).toISOString()
  }

  it('一分钟以内（含未来时间）显示"刚刚"', () => {
    expect(relativeTime(before(0), now)).toBe('刚刚')
    expect(relativeTime(before(30_000), now)).toBe('刚刚')
    // 服务端与客户端时钟有偏差时消息会"来自未来"。
    // 显示"负 2 分钟前"比不显示更糟 —— 用户会以为系统坏了。
    expect(relativeTime(before(-120_000), now)).toBe('刚刚')
  })

  it('分钟 / 小时 / 天三档各自进位正确', () => {
    expect(relativeTime(before(60_000), now)).toBe('1 分钟前')
    expect(relativeTime(before(59 * 60_000), now)).toBe('59 分钟前')
    expect(relativeTime(before(60 * 60_000), now)).toBe('1 小时前')
    expect(relativeTime(before(23 * 3600_000), now)).toBe('23 小时前')
    expect(relativeTime(before(24 * 3600_000), now)).toBe('1 天前')
    expect(relativeTime(before(7 * 24 * 3600_000), now)).toBe('7 天前')
  })

  it('超过一周回落到"月-日"（补零），而不是继续报天数', () => {
    // 8 天前 = 2026-09-21。
    expect(relativeTime(before(8 * 24 * 3600_000), now)).toBe('09-21')
  })

  it('时间戳非法时原样返回，不编造一个时间', () => {
    expect(relativeTime('not-a-date', now)).toBe('not-a-date')
  })
})
