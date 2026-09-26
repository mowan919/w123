/**
 * 展示层表单校验。
 *
 * 这里只做**"能不能提交"的前置提示**，不是权限或安全判定 ——
 * 口令复杂度最终仍由后端 `validate_password_policy` 裁定（`00 §2`）。
 * 前端这份的价值在于：能在用户敲字时就告诉他缺哪一类字符，
 * 而不是提交后被 400 打回来一次。
 *
 * 规则与后端逐条对齐（少一条就会变成"前端说过、后端拒绝"的假阳性）：
 * 长度 ≥ 12、含大写、含小写、含数字、含特殊字符（非字母数字）。
 */
export const PASSWORD_MIN_LENGTH = 12

export interface PasswordCheckInput {
  current?: string
  next: string
  confirm?: string
}

/** 返回第一条不满足的原因；全部通过返回 `null`。 */
export function validatePassword(input: PasswordCheckInput): string | null {
  const { current, next, confirm } = input
  if (current !== undefined && current === '') return '请填写当前口令'
  if (next === '') return '请填写新口令'
  if (confirm !== undefined && next !== confirm) return '两次输入的新口令不一致'
  if (current !== undefined && next === current) return '新口令不能与当前口令相同'
  if (next.length < PASSWORD_MIN_LENGTH) return `新口令至少 ${PASSWORD_MIN_LENGTH} 位`
  if (!/[A-Z]/.test(next)) return '新口令需要包含大写字母'
  if (!/[a-z]/.test(next)) return '新口令需要包含小写字母'
  if (!/[0-9]/.test(next)) return '新口令需要包含数字'
  if (!/[^A-Za-z0-9]/.test(next)) return '新口令需要包含特殊字符'
  return null
}

/** 口令复杂度要求的一句话说明（用于表单下方的提示）。 */
export const PASSWORD_HINT = `至少 ${PASSWORD_MIN_LENGTH} 位，需同时包含大写字母、小写字母、数字与特殊字符`
