import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import FormDialog from '@/components/feedback/FormDialog.vue'

/**
 * 校验提示的**出现时机**。
 *
 * 要钉住的只有一件事：错误提示不能常驻。曾经是实时回显 ——
 * 弹窗一打开、必填项本来就空着，顶部立刻挂一条红字，保存按钮同时变灰。
 * 用户还没动手就先挨一顿数落，而且按钮点不动，连"到底缺什么"都问不出来。
 *
 * 现在是"提交时才开口"：打开干净 → 点保存才说 → 改好了自动消失 →
 * 下次打开重新干净。四条都是**用户可见**的行为，缺一条都会退回到旧观感。
 */

const mounted: VueWrapper[] = []

afterEach(() => {
  while (mounted.length > 0) {
    mounted.pop()?.unmount()
  }
})

async function openDialog(error: string | null): Promise<VueWrapper> {
  // 弹窗内容会被 teleport 到 body，所以必须挂进文档再查。
  const wrapper = mount(FormDialog, {
    props: { open: true, title: '新增用户', error },
    slots: { default: '<label>用户名<input /></label>' },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

function errorAlert(): Element | null {
  return document.querySelector('.form-dialog__error')
}

function saveButton(): HTMLButtonElement {
  const found = Array.from(document.querySelectorAll('button')).find(
    (item) => item.textContent?.trim() === '保存',
  )
  if (found === undefined) throw new Error('找不到保存按钮')
  return found as HTMLButtonElement
}

async function clickSave(): Promise<void> {
  saveButton().dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

describe('FormDialog 的校验提示时机', () => {
  it('打开弹窗时不显示提示 —— 哪怕必填项还是空的', async () => {
    await openDialog('请填写用户名')

    expect(errorAlert()).toBeNull()
    expect(document.body.textContent).not.toContain('请填写用户名')
  })

  it('打开时保存按钮可以点 —— 不能因为"还没填"就先锁死', async () => {
    await openDialog('请填写用户名')

    // 旧实现里 `:disabled="error !== null"` 让按钮一直点不动，
    // 于是"点保存才提示"这条路根本走不到。
    expect(saveButton().disabled).toBe(false)
  })

  it('点了保存才把问题说出来，并且不提交', async () => {
    const wrapper = await openDialog('请填写用户名')

    await clickSave()

    expect(errorAlert()?.textContent).toContain('请填写用户名')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('校验通过时点保存直接提交，全程不出现提示', async () => {
    const wrapper = await openDialog(null)

    await clickSave()

    expect(wrapper.emitted('submit')).toHaveLength(1)
    expect(errorAlert()).toBeNull()
  })

  it('用户改好之后提示自动消失（error 是父组件实时算出来的）', async () => {
    const wrapper = await openDialog('请填写用户名')
    await clickSave()
    expect(errorAlert()).not.toBeNull()

    await wrapper.setProps({ error: null })
    await flushPromises()

    expect(errorAlert()).toBeNull()
  })

  it('重新打开时回到干净状态，上一次的失败不算数', async () => {
    const wrapper = await openDialog('请填写用户名')
    await clickSave()
    expect(errorAlert()).not.toBeNull()

    await wrapper.setProps({ open: false })
    await flushPromises()
    await wrapper.setProps({ open: true })
    await flushPromises()

    expect(errorAlert()).toBeNull()
  })
})
