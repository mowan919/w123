<script setup lang="ts">
/**
 * FormDialog（FE-09 §3）—— 新增 / 编辑的**统一弹窗外壳**。
 *
 * 在它之前，每个页面的新增/编辑都是一个内联在页面底部的编辑区：
 * 打开后要滚到页面最下方才能填写，屏幕小的时候看不到自己点的是哪一行；
 * 关掉它还得再滚回去。弹窗把"编辑态"和"列表态"从视觉上彻底分开。
 *
 * 这里只承载**外壳与动作**（标题 / 提交流程 / 取消 / 校验错误回显），
 * 字段本身由调用方用默认插槽给出 —— 各页面字段差异很大，硬做一套
 * schema 驱动的表单抽象，只会让"这个字段要 disabled""那个字段是下拉"
 * 这类需求无处安放。
 *
 * `NModal` 自带焦点陷阱、Esc 关闭与遮罩滚动锁定。`preset="card"` 会给出
 * 标题栏与底部栏，因此不需要自己画关闭按钮 —— 三条关闭路径（叉 / Esc /
 * 遮罩）都必须发出 `cancel`，否则父组件的 `open` 会停在 true，
 * 表现为"这个弹窗第二次打不开"。
 */
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NModal } from 'naive-ui'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    /** 弹窗宽度；窄屏自动收敛到可视宽度。 */
    width?: number
    /** 提交中：按钮转圈并屏蔽重复提交。 */
    loading?: boolean
    confirmText?: string
    cancelText?: string
    /** 危险表单（删除类）用红色确认按钮。 */
    danger?: boolean
    /**
     * 校验未通过的原因（父组件通常是 computed，随输入实时变化）。
     *
     * ⚠️ 它**不会**在弹窗一打开就显示 —— 只在用户点过保存之后才回显，
     * 见下方 `attempted` 的说明。
     */
    error?: string | null
  }>(),
  {
    width: 560,
    loading: false,
    confirmText: '保存',
    cancelText: '取消',
    danger: false,
    error: null,
  },
)

const emit = defineEmits<{
  (e: 'submit'): void
  (e: 'cancel'): void
}>()

const hasError = computed(() => props.error !== null && props.error !== '')

/**
 * 用户是否**已经尝试过提交**。
 *
 * 这个是"错误提示什么时候出现"的唯一开关。之前是实时回显：弹窗一打开，
 * 必填项本来就还空着，顶部立刻挂一条红字，保存按钮也同时变灰 ——
 * 用户还没动手就先挨一顿数落，而且按钮点不动，连"到底缺什么"都问不出来。
 * 现在改成"提交时才开口"：
 *
 * - 打开弹窗时界面是干净的；
 * - 点了保存（或表单里按 Enter）才把问题说出来；
 * - 用户改好之后红字自动消失 —— 因为 `error` 是父组件的 computed，
 *   条件一旦满足就变 null，这里不需要再监听输入；
 * - 下次重新打开时重置，上一次的失败不该让这一次一开门就挂着红字。
 */
const attempted = ref(false)

watch(
  () => props.open,
  (open) => {
    if (open) attempted.value = false
  },
  { immediate: true },
)

function onClose(): void {
  if (props.loading) return
  emit('cancel')
}

function onSubmit(): void {
  if (props.loading) return
  // 先记下"他试过了"，好让下面的错误条有条件地显形；校验不通过就不提交。
  attempted.value = true
  if (hasError.value) return
  emit('submit')
}
</script>

<template>
  <NModal
    :show="props.open"
    preset="card"
    :title="props.title"
    :style="{ width: `min(${props.width}px, calc(100vw - 32px))` }"
    :mask-closable="!props.loading"
    :close-on-esc="!props.loading"
    @update:show="(value: boolean) => !value && onClose()"
  >
    <form class="form-dialog__body" @submit.prevent="onSubmit">
      <NAlert
        v-if="attempted && hasError"
        type="error"
        :bordered="false"
        class="form-dialog__error"
      >
        {{ props.error }}
      </NAlert>
      <slot />
    </form>

    <template #footer>
      <div class="form-dialog__actions">
        <slot name="extra" />
        <NButton quaternary :disabled="props.loading" @click="onClose">
          {{ props.cancelText }}
        </NButton>
        <NButton
          :type="props.danger ? 'error' : 'primary'"
          :loading="props.loading"
          :disabled="props.loading"
          attr-type="submit"
          @click="onSubmit"
        >
          {{ props.confirmText }}
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.form-dialog__body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-dialog__error {
  margin: 0;
}

.form-dialog__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
</style>
