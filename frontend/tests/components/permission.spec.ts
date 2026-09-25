import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import PermissionButton from '@/components/permission/PermissionButton.vue'
import PermissionField from '@/components/permission/PermissionField.vue'
import { usePermissionStore } from '@/stores/permission'
import { buildContract } from '../helpers/fixtures'

/**
 * 权限组件（FE-09 §4 / FE-03 §6 / FE-05 §3 / FE-12 §2）。
 *
 * 这两个组件只是**展示层**开关。真正的判定仍然在后端；这里的用例反复强调
 * "隐藏 ≠ 拒绝"：按钮不显示时请求照样会 403，反之组件允许点击不代表后端放行。
 */

/** 把 store 装成"当前用户拥有指定按钮/字段权限"的状态。 */
function grant(buttonCodes: string[] = [], fieldLevels: Record<string, string> = {}) {
  const contract = buildContract()
  contract.buttons = buttonCodes.map((code, index) => ({
    id: `8${String(index).padStart(3, '0')}`,
    code,
    name: code,
    parent_id: null,
    sort_order: index,
  }))
  contract.fields = Object.entries(fieldLevels).map(([fieldKey, accessLevel], index) => ({
    id: `6${String(index).padStart(3, '0')}`,
    code: `field:${fieldKey}`,
    field_key: fieldKey,
    owner_resource_id: null,
    access_level: accessLevel as 'VISIBLE' | 'HIDDEN' | 'READ_ONLY' | 'EDITABLE',
  }))
  usePermissionStore().apply(contract)
}

describe('PermissionButton', () => {
  it('hide 模式下无权限不渲染', () => {
    grant([])
    const wrapper = mount(PermissionButton, { props: { code: 'user:create' } })
    // 不能断言 `html() === ''`：Vue 的 `v-if` 会留一个注释锚点
    // （'<!--v-if-->'），那不等于"没渲染"。真正要说的是"没有按钮、也没内容"。
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('hide 模式下有权限正常渲染', () => {
    grant(['user:create'])
    const wrapper = mount(PermissionButton, { props: { code: 'user:create' } })
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('disable 模式下无权限也渲染，但处于禁用态', () => {
    grant([])
    const wrapper = mount(PermissionButton, {
      props: { code: 'user:create', mode: 'disable' },
      slots: { default: () => '新增' },
    })
    expect(wrapper.find('button').exists()).toBe(true)
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  })

  it('无权限时点击不触发事件（前端先把口子堵上）', async () => {
    grant([])
    const wrapper = mount(PermissionButton, {
      props: { code: 'user:create', mode: 'disable' },
      slots: { default: () => '新增' },
    })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('click')).toBeUndefined()
  })

  it('有权限且未禁用时点击**只**触发一次事件', async () => {
    // 这条锁的是 `emits` 必须声明：漏了 `defineEmits` 时，根元素上的模板
    // `@click` 与"$emit 未声明时的 fallthrough 合并"路径各触发一次，
    // 一次点击会派发两个 `click` —— 父组件 `@click="save"` 就被调两遍。
    // 表现是偶发的重复提交，肉眼在模板里完全看不出来。
    grant(['user:create'])
    const wrapper = mount(PermissionButton, {
      props: { code: 'user:create' },
      slots: { default: () => '新增' },
    })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('loading 期间不触发事件（防止重复提交）', async () => {
    grant(['user:create'])
    const wrapper = mount(PermissionButton, {
      props: { code: 'user:create', loading: true },
      slots: { default: () => '保存' },
    })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('click')).toBeUndefined()
  })

  it('没有权限的按钮不代表后端会放行：绕过组件直接请求依然会被拒', () => {
    // 这条用例锁的是 FE-03 §6：隐藏只是展示层，后端才是最终兜底。
    // 后端侧对应 `test_permission_matrix.py` 里的 403 用例。
    grant([])
    expect(usePermissionStore().hasButtonPermission('user:delete')).toBe(false)
  })
})

describe('PermissionField', () => {
  it('HIDDEN 不渲染', () => {
    grant([], { 'user.internal_note': 'HIDDEN' })
    const wrapper = mount(PermissionField, {
      props: { code: 'user.internal_note' },
      slots: { default: () => '不该出现' },
    })
    // 同样不能断言 `html() === ''`：`v-if` 会留注释锚点。
    expect(wrapper.find('.permission-field').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('未声明的键按 HIDDEN 处理（未知键不该默认可见）', () => {
    grant([], { 'user.email': 'EDITABLE' })
    const wrapper = mount(PermissionField, {
      props: { code: 'user.unknown' },
      slots: { default: () => '不该出现' },
    })
    expect(wrapper.find('.permission-field').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('EDITABLE 渲染且可编辑', () => {
    grant([], { 'user.email': 'EDITABLE' })
    const wrapper = mount(PermissionField, {
      props: { code: 'user.email' },
      slots: {
        default: (params: { editable: boolean }) =>
          h('span', null, `editable=${String(params.editable)}`),
      },
    })
    expect(wrapper.text()).toBe('editable=true')
    expect(wrapper.classes()).not.toContain('is-readonly')
  })

  it('READ_ONLY 渲染但不可编辑', () => {
    grant([], { 'user.phone': 'READ_ONLY' })
    const wrapper = mount(PermissionField, {
      props: { code: 'user.phone' },
      slots: {
        default: (params: { editable: boolean; level: string }) =>
          h('span', null, `${params.level}/editable=${String(params.editable)}`),
      },
    })
    expect(wrapper.text()).toBe('READ_ONLY/editable=false')
    expect(wrapper.classes()).toContain('is-readonly')
  })

  it('VISIBLE 渲染且不可编辑', () => {
    grant([], { 'user.remark': 'VISIBLE' })
    const wrapper = mount(PermissionField, {
      props: { code: 'user.remark' },
      slots: {
        default: (params: { editable: boolean }) => h('span', null, String(params.editable)),
      },
    })
    expect(wrapper.text()).toBe('false')
  })

  it('把访问级别透传给插槽，供调用方自行决定控件形态', () => {
    grant([], { 'user.email': 'EDITABLE' })
    const wrapper = mount(PermissionField, {
      props: { code: 'user.email' },
      slots: { default: (params: { level: string }) => h('span', null, params.level) },
    })
    expect(wrapper.text()).toBe('EDITABLE')
  })
})
