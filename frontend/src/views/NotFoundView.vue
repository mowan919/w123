<script setup lang="ts">
/** 404。 */
</script>

<template>
  <div class="not-found">
    <h1>404</h1>
    <p>页面不存在，或者你没有访问权限。</p>
    <a class="btn" href="/dashboard">返回概览</a>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 80px 16px;
}

.not-found h1 {
  font-size: 56px;
  color: var(--vctn-text-weak);
}
</style>
