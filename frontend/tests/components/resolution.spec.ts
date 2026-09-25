import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 模板里引用的组件，必须真的被导入（`08 §3` 起的权利组件化了之后新增的风险）。
 *
 * 为什么需要这个测试，而不是"看一眼就好"：
 *
 * `UserListView` 曾经在模板里写了 `<PermissionField>`，却忘了导入。Vue 不报错、
 * 不崩溃，只在 console 里打一句 "Failed to resolve component"，然后把它当成一个
 * 未知原生元素渲染 —— 结果是**字段级权限的 UI 门控整个失效**，而所有测试全绿
 * （当时的测试根本没挂这个视图）。这类缺陷不会让任何一个断言变红，只会让一道
 * 防线悄悄不存在。
 *
 * 静态扫描比"每个视图都挂一遍"便宜得多，也严得多：挂载一次只能证明那一个视图
 * 的那一处引用对，扫描能一次覆盖全部 `*.vue`。
 */

const SRC = join(process.cwd(), 'src')
const VIEW_EXT = '.vue'

/**
 * 全局注册的组件：由 `app.use(router)` 带来（`vue-router` 会注册
 * `RouterView` / `RouterLink`）。这里不重复注册它们，所以不要求导入。
 */
const GLOBALLY_REGISTERED = new Set(['RouterView', 'RouterLink'])

function collect(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      out.push(...collect(full))
    } else if (entry.endsWith(VIEW_EXT)) {
      out.push(full)
    }
  }
  return out
}

/** 从一份 `.vue` 里取出"模板用到的标签名"。 */
function templateTags(source: string): Set<string> {
  const start = source.indexOf('<template>')
  const end = source.lastIndexOf('</template>')
  const template = start >= 0 && end > start ? source.slice(start + 9, end) : ''
  const tags = new Set<string>()
  // 只认真正的开标签 / 自闭合标签名；`:rows="rows as Role[]"` 这类类型注解
  // 出现在属性字符串里，不会被这条规则误伤（它们的前面是 `:`，不是 `<`）。
  for (const match of template.matchAll(/<\s*([A-Za-z-]+:)?([A-Z][A-Za-z0-9]*)(?=[\s/>])/g)) {
    tags.add(match[2] ?? '')
  }
  return tags
}

/** 从一份 `.vue` 里取出"导入进作用域的名字"（含别名）。 */
function importedNames(source: string): Set<string> {
  const names = new Set<string>()
  const importRe = /import\s+(?:type\s+)?([\s\S]*?)\s*from\s*['"][^'"]+['"]/g
  for (const match of source.matchAll(importRe)) {
    const clause = match[1] ?? ''
    const braces = clause.match(/\{([\s\S]*?)\}/)
    if (braces?.[1]) {
      for (const part of braces[1].split(',')) {
        const alias = part.trim().split(/\s+as\s+/).pop()?.trim()
        if (alias) names.add(alias)
      }
    }
    const direct = clause.replace(/\{[\s\S]*?\}/, '').replace(/,/g, '').trim()
    if (/^[A-Z][A-Za-z0-9]*$/.test(direct)) names.add(direct)
  }
  return names
}

describe('组件解析', () => {
  const files = collect(SRC)

  it('扫描到的是全部视图文件（防止路径写错后空跑）', () => {
    expect(files.length).toBeGreaterThan(10)
  })

  /**
   * 这条是最关键的断言。
   *
   * `<script setup>` 里**没有** `components` 选项可配 —— 组件只能靠 import 进
   * 作用域，漏了就是"静默不渲染"。
   */
  it('模板引用的每个组件都必须已导入，否则 Vue 会静默渲染成空元素', () => {
    const unresolved: string[] = []
    for (const file of files) {
      const source = readFileSync(file, 'utf8')
      const imported = importedNames(source)
      for (const tag of templateTags(source)) {
        if (!imported.has(tag) && !GLOBALLY_REGISTERED.has(tag)) {
          unresolved.push(`${file.replace(/\\/g, '/')} → <${tag}>`)
        }
      }
    }
    expect(unresolved).toEqual([])
  })
})
