<script setup lang="ts">
/** 403（FE-04 §4）：权限不足，**不是**登录失效。 */
</script>

<template>
  <div class="forbidden">
    <h1>403</h1>
    <p>你没有访问该功能的权限。</p>
    <p class="muted">如果你认为应当有权限，请联系管理员在后台为该角色授权。</p>
    <a class="btn" href="/dashboard">返回概览</a>
  </div>
</template>

<style scoped>
.forbidden {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 80px 16px;
}

.forbidden h1 {
  font-size: 56px;
  color: var(--vctn-text-weak);
}
</style>
