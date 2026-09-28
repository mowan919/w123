import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { h } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { DOMWrapper, VueWrapper } from '@vue/test-utils'
import DataTable from '@/components/data/DataTable.vue'
import type { DataTableColumn } from '@/components/data/types'

/**
 * 列表"列多时不折行、操作列固定在右侧"的契约。
 *
 * ⚠️ **本文件的覆盖边界**：`white-space: nowrap` 与 `position: sticky` 的实际
 * 布局效果 jsdom **不做**（它不算布局），所以这里分两层钉：
 *
 * 1. **DOM 契约**（本文件的下半部分）：CSS 依赖的结构必须先存在 ——
 *    `.clip` 包裹、`td[title]`、`col-actions` 类名。类名没了，CSS 再对也选不中。
 * 2. **样式契约**（本文件的下半部分之后）：直接读 `base.css`，钉住那几条
 *    声明本身不被删掉。
 *
 * 真实的渲染结果（不折行、横向滚动、滚动后操作列仍在视野内）已在 Chrome
 * headless 里以 1400px / 984px 两个宽度实测确认，量到的数字是
 * `container.clientWidth=1324 < scrollWidth=1796`、各列折行数全为 `1`、
 * `td.col-actions.position=sticky` 且滚动后仍在容器右缘内。
 * jsdom 里造不出这份证据，因此不在这里假装测了。
 */

interface Row {
  username: string
  note: string
}

const columns: Array<DataTableColumn<Row>> = [
  { key: 'username', title: '用户名' },
  { key: 'note', title: '备注' },
]

const rows: Row[] = [{ username: 'admin', note: '系统管理员' }]

const mounted: VueWrapper[] = []

afterEach(() => {
  while (mounted.length > 0) {
    mounted.pop()?.unmount()
  }
})

function render(
  props: Record<string, unknown> = {},
  slots?: Record<string, unknown>,
): VueWrapper {
  // DataTable 是**泛型组件**（`<script setup generic="T">`）。`mount` 无法从 props
  // 反推 `T`，T 会落成 `unknown`，于是 `columns: DataTableColumn<Row>[]` 与
  // `rowKey: (row: Row) => string` 一并被判为不兼容。
  // 这里关心的是"渲染出来什么"，"列与行是否同型"由各页面在编译期保证，
  // 所以把挂载参数整体放宽 —— 而不是在每个用例里撒 cast。
  const options = {
    props: { columns, rows, rowKey: (row: Row) => row.username, ...props },
    ...(slots === undefined ? {} : { slots }),
  }
  const wrapper = mount(DataTable, options as never) as unknown as VueWrapper
  mounted.push(wrapper)
  return wrapper
}

function firstBodyRow(wrapper: VueWrapper): DOMWrapper<Element> {
  const found = wrapper.findAll('tbody tr')[0]
  if (found === undefined) throw new Error('没有数据行')
  return found
}

describe('DataTable —— 单元格渲染契约', () => {
  it('默认渲染的单元格内容被 `.clip` 包裹（截断样式的落点）', () => {
    const notes = firstBodyRow(render()).findAll('td')[1]
    const clip = notes?.find('.clip')

    expect(clip?.exists()).toBe(true)
    expect(clip?.text()).toBe('系统管理员')
  })

  it('默认渲染的单元格带 `title`，截断后仍能悬停看完整值', () => {
    const notes = firstBodyRow(render()).findAll('td')[1]

    expect(notes?.attributes('title')).toBe('系统管理员')
  })

  it('空值渲染成 `—`，且提示与画面一致', () => {
    const wrapper = render({ rows: [{ username: 'admin', note: null as unknown as string }] })
    const notes = firstBodyRow(wrapper).findAll('td')[1]

    expect(notes?.text()).toBe('—')
    expect(notes?.attributes('title')).toBe('—')
  })

  it('自定义渲染的单元格**不给** `title`（避免提示与画面不符）', () => {
    // 真实场景：`status` 字段的值是 `ACTIVE`，页面上显示"正常"。
    // 若 DataTable 硬塞原值当提示，悬停会看到与画面不符的英文枚举 ——
    // 比没有提示更糟，所以这类列由页面自己决定要不要给 title。
    const wrapper = render({}, { 'cell-note': () => h('span', { class: 'label' }, '正常') })
    const notes = firstBodyRow(wrapper).findAll('td')[1]

    expect(notes?.find('.label').exists()).toBe(true)
    expect(notes?.attributes('title')).toBeUndefined()
    // 同时确认它没有被 DataTable 再包一层 `.clip`（页面自己渲染的内容不受管）
    expect(notes?.find('.clip').exists()).toBe(false)
  })

  it('字符串模板槽同样生效（不是字符串被静默丢弃）', () => {
    // 这一条是**探测**用：若 `vue` 被解析成不带编译器的运行时构建，
    // 字符串模板会被静默忽略、槽变空，而所有"查槽内容"的断言都会失败得
    // 莫名其妙。其它测试文件里有用字符串写槽的，所以这里明确钉一下。
    const wrapper = render({}, { 'cell-note': '<span class="label">正常</span>' })
    const notes = firstBodyRow(wrapper).findAll('td')[1]

    expect(notes?.find('.label').text()).toBe('正常')
  })

  it('列的 `width` / `align` 落到表头与单元格上', () => {
    const wrapper = render({
      columns: [
        { key: 'username', title: '用户名', width: '120px', align: 'right' },
        { key: 'note', title: '备注' },
      ] as Array<DataTableColumn<Row>>,
    })

    const head = wrapper.findAll('th')[0]
    expect(head?.attributes('style')).toContain('width: 120px')
    expect(head?.classes()).toContain('is-right')
    expect(firstBodyRow(wrapper).findAll('td')[0]?.classes()).toContain('is-right')
  })
})

describe('DataTable —— 操作列', () => {
  it('传了 `actions-title` 才渲染操作列，且落在最后一列', () => {
    const without = render()
    expect(without.find('.col-actions').exists()).toBe(false)

    const withActions = render({ actionsTitle: '操作', actionsWidth: '180px' })
    const heads = withActions.findAll('th')
    expect(heads[heads.length - 1]?.classes()).toContain('col-actions')
    expect(heads[heads.length - 1]?.text()).toBe('操作')
    expect(heads[heads.length - 1]?.attributes('style')).toContain('width: 180px')

    const cells = firstBodyRow(withActions).findAll('td')
    expect(cells[cells.length - 1]?.classes()).toContain('col-actions')
  })

  it('操作列**不**套 `.clip`（按钮被截断等于点不到）', () => {
    const wrapper = render(
      { actionsTitle: '操作' },
      { actions: () => h('button', { type: 'button' }, '编辑') },
    )
    const actions = firstBodyRow(wrapper).findAll('td').at(-1)

    expect(actions?.find('.clip').exists()).toBe(false)
    expect(actions?.find('button').exists()).toBe(true)
  })

  it('操作列默认**居中**（表头与单元格都带 `is-center`）', () => {
    // 居中的理由：左对齐时"编辑 / 重置口令 / 禁用"与只有"编辑"的行各自贴左，
    // 每个动作的横向位置随该行按钮多少而变；居中后位置稳定。
    const wrapper = render({ actionsTitle: '操作' })

    expect(wrapper.findAll('thead th').at(-1)?.classes()).toContain('is-center')
    expect(firstBodyRow(wrapper).findAll('td').at(-1)?.classes()).toContain('is-center')
  })

  it('显式传 `actions-align` 时以传入值为准（居中不是写死在 CSS 里的）', () => {
    // 这条防的是"把 center 写进 base.css"：那样传 left 的页面会静默失效，
    // 而且看不出是哪儿改的 —— 页面里的 prop 还在，只是不再起作用。
    const wrapper = render({ actionsTitle: '操作', actionsAlign: 'left' })

    expect(wrapper.findAll('thead th').at(-1)?.classes()).not.toContain('is-center')
    expect(firstBodyRow(wrapper).findAll('td').at(-1)?.classes()).not.toContain('is-center')
  })
})

describe('DataTable —— 四态', () => {
  it('loading / error / empty 各自只渲染一种状态，不出表格', () => {
    const loading = render({ loading: true })
    expect(loading.find('table').exists()).toBe(false)

    const failed = render({ error: '加载失败' })
    expect(failed.find('table').exists()).toBe(false)
    expect(failed.text()).toContain('加载失败')

    const empty = render({ rows: [] })
    expect(empty.find('table').exists()).toBe(false)
    expect(empty.text()).toContain('暂无数据')
  })

  it('有数据时不渲染空态（`rows` 非空优先）', () => {
    const wrapper = render()

    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('暂无数据')
  })
})

/**
 * 样式契约：这些声明一旦被删，"列多时不折行 / 操作列固定在右侧"就会**静默**
 * 退回旧观感 —— jsdom 测不出来，人工也未必每次都会在浏览器里看。
 * 所以直接读 `base.css` 把声明本身钉住。
 *
 * 断言前先把空白折叠，因此换行与缩进怎么调都不影响，但**删除或改值会红**。
 */
describe('DataTable —— 样式契约（base.css）', () => {
  // 路径相对 `frontend/`（vitest 的工作目录）解析；不用 `new URL(import.meta.url)`
  // 是因为本机的 fs 垫片不接受 `file://` URL 对象。
  //
  // 先剥掉注释再折叠空白：注释里会出现 `{ width: 100% }` 这种片段，
  // 不剥掉的话下面按**第一个 `}`** 截断声明体的做法会被它提前截断
  // （这条是实测踩出来的 —— 第一版 `body()` 正是这么失效的）。
  const css = readFileSync(resolve(process.cwd(), 'src/styles/base.css'), 'utf8')
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\s+/g, ' ')

  /** 取某条规则的声明体；注释与空白已折叠，不受换行、缩进、注释影响。 */
  function body(selector: string): string {
    const needle = `${selector.replace(/\s+/g, ' ')} {`
    const start = flat.indexOf(needle)
    if (start < 0) throw new Error(`base.css 里没有这条规则：${selector}`)
    return flat.slice(start + needle.length, flat.indexOf('}', start))
  }

  it('单元格与表头都声明 `white-space: nowrap`', () => {
    expect(body('.data-table__table th, .data-table__table td')).toContain('white-space: nowrap')
  })

  it('操作列 `position: sticky` + `right: 0`，并有不透明背景', () => {
    const rule = body('.data-table__table td.col-actions, .data-table__table th.col-actions')

    expect(rule).toContain('position: sticky')
    expect(rule).toContain('right: 0')
    // sticky 没有不透明背景时，滚到它下面的列会直接透出来。
    expect(rule).toContain('background: var(--vctn-surface)')
  })

  it('操作列钉住的底色与行 hover 的底色一致', () => {
    // 两者不一致时，hover 一整行会看到操作列那一格颜色不一样。
    const rowHover = body('.data-table__table tbody tr:hover')
    const actionsHover = body(
      '.data-table__table tbody tr:hover .col-actions, .data-table__table tbody tr:focus-within .col-actions',
    )

    expect(rowHover).toContain('background: var(--vctn-fill-subtle)')
    expect(actionsHover).toContain('background: var(--vctn-fill-subtle)')
  })

  it('窄屏（≤1080px）取消固定，但保留横向滚动', () => {
    const narrowRule =
      '.data-table__table td.col-actions, .data-table__table th.col-actions { position: static;'

    expect(flat).toContain(narrowRule)
    // 横向滚动的载体是容器，窄屏也不能取消它。
    expect(body('.data-table')).toContain('overflow-x: auto')
  })

  it('`.clip` 提供截断能力（超长文本不靠折行解决）', () => {
    const rule = body('.clip')

    expect(rule).toContain('overflow: hidden')
    expect(rule).toContain('text-overflow: ellipsis')
    expect(rule).toContain('white-space: nowrap')
  })

  it('单元格同时有横向与竖向分割线', () => {
    const rule = body('.data-table__table th, .data-table__table td')

    expect(rule).toContain('border-bottom: 1px solid var(--vctn-border)')
    // 只用 border-left（不用 border-right）：`border-collapse: separate` 下
    // 相邻单元格的两条边会并排出现、把界线变成 2px。
    expect(rule).toContain('border-left: 1px solid var(--vctn-border)')
    expect(rule).not.toContain('border-right')
  })

  it('首列不画左分割线（否则贴着容器边框会出现双线）', () => {
    // 用 `tr > *:first-child` 而不是 `td:first-child`：有勾选列时首列是
    // `th` / `td.col-select`，两种都要覆盖。
    expect(body('.data-table__table tr > *:first-child')).toContain('border-left: none')
  })

  it('抽屉里的次级表格（`.mini-table`）同样横竖都画线', () => {
    const rule = body('.mini-table th, .mini-table td')

    expect(rule).toContain('border-bottom: 1px solid var(--vctn-border)')
    expect(rule).toContain('border-left: 1px solid var(--vctn-border)')
    expect(body('.mini-table tr > *:first-child')).toContain('border-left: none')
  })

  it('操作列不再整体压暗（"有权限的按钮要显眼"）', () => {
    // 旧实现给整列 `opacity: 0.72`，把"有权限才渲染出来的按钮"和
    // "没权限被隐藏"这两件事在观感上抹平了：能点的也灰着。
    expect(flat).not.toContain('opacity: 0.72')
  })
})

describe('base.css —— 文字按钮的彩色变体', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/styles/base.css'), 'utf8')
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\s+/g, ' ')

  function body(selector: string): string {
    const needle = `${selector.replace(/\s+/g, ' ')} {`
    const start = flat.indexOf(needle)
    if (start < 0) throw new Error(`base.css 里没有这条规则：${selector}`)
    return flat.slice(start + needle.length, flat.indexOf('}', start))
  }

  it('四种语义色各自声明了颜色', () => {
    expect(body('.btn--text-primary')).toContain('color: var(--vctn-primary)')
    expect(body('.btn--text-success')).toContain('color: var(--vctn-success)')
    expect(body('.btn--text-warn')).toContain('color: var(--vctn-warn)')
    expect(body('.btn--text-danger')).toContain('color: var(--vctn-danger)')
  })

  it('每个彩色变体都有 `:hover` 覆盖', () => {
    // 没有它时 `.btn:hover:not(.is-disabled)`（权重 0,3,0）会把所有彩色按钮
    // 一悬停都染成主色蓝 —— 肉眼很容易当成"设计如此"。
    for (const tone of ['primary', 'success', 'warn', 'danger']) {
      expect(flat).toContain(`.btn--text-${tone}:hover:not(.is-disabled) {`)
    }
  })
})
