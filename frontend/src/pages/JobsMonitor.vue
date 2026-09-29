<script setup lang="ts">
defineOptions({ name: 'JobsMonitor' })
import { ref, computed, onMounted, h } from 'vue'
import {
  NIcon, NButton, NTag, NCard, NSpace, NGrid, NGridItem, NEmpty, NDataTable,
  NCollapse, NCollapseItem, NSpin, useMessage,
} from 'naive-ui'
import {
  TimeOutline, RefreshOutline, PlayOutline, CheckmarkCircleOutline,
  CloseCircleOutline, HourglassOutline, InformationCircleOutline,
} from '@vicons/ionicons5'
import { api } from '../utils/api'
import PageHeader from '../components/PageHeader.vue'
import type { JobInfo, JobRun } from '../types'

const message = useMessage()
const jobs = ref<JobInfo[]>([])
const loading = ref(false)
const lastRefresh = ref<string>('')
const runningIds = ref<Set<string>>(new Set())

const JOB_TYPE_LABEL: Record<string, string> = {
  scheduled: '定时',
  manual: '手动',
  startup: '启动',
  unknown: '未知',
}

const statusType = (s: JobInfo['last_status']) =>
  s === 'success' ? 'success' : s === 'failed' ? 'error' : s === 'running' ? 'warning' : 'default'

const statusIcon = (s: JobInfo['last_status']) => {
  if (s === 'success') return CheckmarkCircleOutline
  if (s === 'failed') return CloseCircleOutline
  if (s === 'running') return HourglassOutline
  return InformationCircleOutline
}

async function loadJobs() {
  loading.value = true
  try {
    jobs.value = await api.getJobs()
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (e) {
    message.error('加载任务状态失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    loading.value = false
  }
}

async function runJob(job: JobInfo) {
  runningIds.value = new Set(runningIds.value).add(job.job_id)
  try {
    const res = await api.runJob(job.job_id)
    if (res.ok) {
      message.success(`${job.name}：${res.message}`)
      // 触发后稍等再刷新，让状态/近期记录更新
      setTimeout(loadJobs, 1200)
    } else {
      message.warning(`${job.name}：${res.message}`)
    }
  } catch (e) {
    message.error('触发失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    const next = new Set(runningIds.value)
    next.delete(job.job_id)
    runningIds.value = next
  }
}

onMounted(loadJobs)

// 近期执行记录表列
const runColumns = [
  { title: '开始时间', key: 'started_at', width: 160 },
  { title: '结束时间', key: 'finished_at', width: 160,
    render: (row: JobRun) => row.finished_at ?? '—' },
  { title: '状态', key: 'status', width: 90,
    render: (row: JobRun) => h(NTag, { type: statusType(row.status), size: 'small' }, { default: () => row.status }) },
  { title: '耗时', key: 'duration_ms', width: 100,
    render: (row: JobRun) => (row.duration_ms != null ? `${row.duration_ms} ms` : '—') },
  { title: '错误信息', key: 'error',
    render: (row: JobRun) => row.error ?? '—' },
]
</script>

<template>
  <div class="jobs-page">
    <PageHeader title="后台任务监控" subtitle="定时任务与后台任务的执行状态、耗时与近期运行记录">
      <template #actions>
        <n-button size="small" :loading="loading" @click="loadJobs">
          <template #icon><n-icon :component="RefreshOutline" /></template>
          刷新
        </n-button>
      </template>
    </PageHeader>

    <div class="refresh-hint" v-if="lastRefresh">
      最后刷新：{{ lastRefresh }}
    </div>

    <NSpin :show="loading && jobs.length === 0">
      <NEmpty v-if="!loading && jobs.length === 0" description="暂无已注册的后台任务" />

      <NGrid v-else :cols="1" :x-gap="14" :y-gap="14" responsive="screen" item-responsive>
        <NGridItem v-for="job in jobs" :key="job.job_id" span="1">
          <NCard :title="job.name" size="small" :segmented="{ content: true }">
            <template #header-extra>
              <NSpace :size="6" align="center">
                <NTag size="small" :bordered="false" type="info">{{ JOB_TYPE_LABEL[job.job_type] || job.job_type }}</NTag>
                <NTag size="small" :bordered="false" :type="statusType(job.last_status)"
                      :icon="() => h(NIcon, { component: statusIcon(job.last_status) })">
                  {{ job.last_status_label }}
                </NTag>
              </NSpace>
            </template>

            <div class="job-body">
              <div class="job-meta">
                <div class="meta-row"><span class="meta-label">调度</span><span class="meta-value">{{ job.schedule }}</span></div>
                <div class="meta-row"><span class="meta-label">上次运行</span><span class="meta-value">{{ job.last_run_at ?? '—' }}</span></div>
                <div class="meta-row"><span class="meta-label">下次运行</span><span class="meta-value">{{ job.next_run_at ?? '—' }}</span></div>
                <div class="meta-row">
                  <span class="meta-label">耗时</span>
                  <span class="meta-value">{{ job.last_duration_ms != null ? job.last_duration_ms + ' ms' : '—' }}</span>
                </div>
                <div class="meta-row">
                  <span class="meta-label">累计</span>
                  <span class="meta-value">运行 {{ job.run_count }} 次 / 失败 {{ job.fail_count }} 次</span>
                </div>
                <div class="meta-row" v-if="job.last_error">
                  <span class="meta-label">错误</span><span class="meta-value err">{{ job.last_error }}</span>
                </div>
              </div>

              <div class="job-actions">
                <n-button
                  v-if="job.triggerable"
                  size="small"
                  type="primary"
                  ghost
                  :loading="runningIds.has(job.job_id)"
                  @click="runJob(job)"
                >
                  <template #icon><n-icon :component="PlayOutline" /></template>
                  立即运行
                </n-button>
              </div>
            </div>

            <NCollapse v-if="job.recent_runs.length" display-directive="show">
              <NCollapseItem title="近期执行记录" :name="job.job_id">
                <NDataTable
                  :columns="runColumns"
                  :data="job.recent_runs"
                  :row-key="(row: JobRun) => row.started_at"
                  size="small"
                  :max-height="240"
                  :bordered="false"
                />
              </NCollapseItem>
            </NCollapse>
          </NCard>
        </NGridItem>
      </NGrid>
    </NSpin>
  </div>
</template>

<style scoped>
.jobs-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.refresh-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.job-body {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.job-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 240px;
}

.meta-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
}

.meta-label {
  width: 56px;
  flex-shrink: 0;
  color: var(--text-muted);
}

.meta-value {
  color: var(--text-primary);
  word-break: break-all;
}

.meta-value.err {
  color: var(--color-danger);
}

.job-actions {
  flex-shrink: 0;
}
</style>
