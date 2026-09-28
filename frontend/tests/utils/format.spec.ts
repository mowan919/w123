import { afterEach, describe, expect, it, vi } from 'vitest'
import { formatDateTime, localInputToUtcIso, nowAsLocalInput } from '@/utils/format'

/**
 * 时间展示与"时间筛选"的取值转换。
 *
 * 这组用例守的是一条**不会报错**的错误：`<input type="datetime-local">`
 * 的 value 是**不带时区**的本地时间串，把它原样发给后端时，
 * 后端会把它解析成 naive datetime 再绑到 `timestamptz` 列上比较 ——
 * 此时"它算几点"由**服务端时区**决定，而不是浏览器时区。
 * 实测本机 `TimeZone=Asia/Shanghai`：naive `09:35` 被当成 `01:35+00:00`。
 * 所以服务器一旦不在 +08:00，筛选会整块偏移且**一个错都不报**。
 */

afterEach(() => {
  vi.useRealTimers()
})

describe('localInputToUtcIso', () => {
  it('空串返回 null（调用方据此不发这个参数，而不是发个空串）', () => {
    expect(localInputToUtcIso('')).toBeNull()
  })

  it('非法输入返回 null，不抛异常', () => {
    expect(localInputToUtcIso('不是时间')).toBeNull()
    expect(localInputToUtcIso('2026-13-45T99:99')).toBeNull()
  })

  it('结果带 UTC 标记 —— 这正是"不再依赖服务端时区"的原因', () => {
    const iso = localInputToUtcIso('2026-09-28T09:00')

    expect(iso).not.toBeNull()
    // 不带 `Z` / 偏移的串到了后端又会被当成 naive，问题原封不动。
    expect(iso?.endsWith('Z')).toBe(true)
  })

  it('按**本地时区**解释输入：往返后墙钟时间不变', () => {
    // 不断言具体 UTC 值（那会随运行机器的时区变化），
    // 而是断言"用户输入几点，回读就是几点" —— 这才是筛选该有的语义。
    for (const raw of ['2026-09-28T09:00', '2026-01-01T00:00', '2026-12-31T23:59']) {
      const iso = localInputToUtcIso(raw)
      const back = new Date(iso as string)
      const [date, time] = raw.split('T')
      const expected = `${date}T${time}`
      const pad = (n: number): string => String(n).padStart(2, '0')
      const actual =
        `${back.getFullYear()}-${pad(back.getMonth() + 1)}-${pad(back.getDate())}` +
        `T${pad(back.getHours())}:${pad(back.getMinutes())}`
      expect(actual).toBe(expected)
    }
  })

  it('带秒的值同样能往返（`step` 设成 1 时浏览器会带上秒）', () => {
    const iso = localInputToUtcIso('2026-09-28T09:00:30')
    const back = new Date(iso as string)

    expect(back.getSeconds()).toBe(30)
  })
})

describe('nowAsLocalInput', () => {
  it('格式可以直接回填进 `datetime-local`', () => {
    vi.useFakeTimers({ now: new Date(2026, 8, 28, 17, 33, 45) })

    expect(nowAsLocalInput()).toBe('2026-09-28T17:33')
  })

  it('个位数的月 / 日 / 时 / 分补零（否则 input 会当成空值丢弃）', () => {
    // `<input type="datetime-local">` 只接受 `YYYY-MM-DDTHH:mm`，
    // `2026-1-5T9:07` 这种会被浏览器判为非法并显示为空 ——
    // 用户点「此刻」后什么都不会发生，且没有任何提示。
    vi.useFakeTimers({ now: new Date(2026, 0, 5, 9, 7, 0) })

    expect(nowAsLocalInput()).toBe('2026-01-05T09:07')
  })

  it('与 `localInputToUtcIso` 配对后落在"现在"附近', () => {
    vi.useRealTimers()
    const before = Date.now()
    const iso = localInputToUtcIso(nowAsLocalInput())
    const after = Date.now()

    expect(iso).not.toBeNull()
    const stamp = new Date(iso as string).getTime()
    // 精确到分钟，所以允许前后各一分钟的误差。
    expect(stamp).toBeGreaterThanOrEqual(before - 60_000)
    expect(stamp).toBeLessThanOrEqual(after + 60_000)
  })
})

describe('formatDateTime', () => {
  it('ISO 串转本地时间显示，空值给占位符', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('')).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
  })

  it('非法输入原样返回，而不是 `Invalid Date`', () => {
    expect(formatDateTime('不是时间')).toBe('不是时间')
  })
})
