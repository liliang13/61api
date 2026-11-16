<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">消息管理</h1>
      <el-button type="primary" @click="openEdit(null)">发布消息</el-button>
    </div>
    <p class="mt-2 text-xs text-stone-400">发布后面向全体用户展示,用户端右上角铃铛会提示未读数</p>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <p class="text-sm font-semibold text-stone-700">{{ row.title }}</p>
            <p class="truncate text-xs text-stone-400">{{ row.body_preview }}</p>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.status === 1 ? 'success' : 'info'">
              {{ row.status === 1 ? '已发布' : '已下架' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="已读人数" width="100" align="center">
          <template #default="{ row }">{{ row.read_count }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="发布时间" width="165" />
        <el-table-column label="操作" width="200" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.status === 1" link type="warning" @click="toggle(row, 0)">下架</el-button>
            <el-button v-else link type="success" @click="toggle(row, 1)">上架</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" />
    </div>

    <el-dialog v-model="edit.visible" :title="edit.form.id ? '编辑消息' : '发布消息'" width="560">
      <el-form label-position="top">
        <el-form-item label="标题" required>
          <el-input v-model="edit.form.title" maxlength="128" placeholder="消息标题" show-word-limit />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input v-model="edit.form.body" type="textarea" :rows="8" maxlength="20000"
            placeholder="消息正文(支持换行)" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.visible = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="saveEdit">{{ edit.form.id ? '保存' : '发布' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminCreateNotice, adminDeleteNotice, adminNotices, adminUpdateNotice,
} from '../../api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 15
const edit = reactive({ visible: false, saving: false, form: { id: null, title: '', body: '' } })

async function load() {
  const res = await adminNotices({ page: page.value, page_size: size })
  items.value = res.data?.items || []
  total.value = res.data?.total || 0
}

function openEdit(row) {
  edit.form = row
    ? { id: row.id, title: row.title, body: row.body }
    : { id: null, title: '', body: '' }
  edit.visible = true
}

async function saveEdit() {
  if (!edit.form.title?.trim() || !edit.form.body?.trim()) {
    ElMessage.warning('请填写标题和正文')
    return
  }
  edit.saving = true
  try {
    if (edit.form.id) await adminUpdateNotice(edit.form.id, edit.form)
    else await adminCreateNotice(edit.form)
    ElMessage.success(edit.form.id ? '已保存' : '已发布')
    edit.visible = false
    await load()
  } finally { edit.saving = false }
}

async function toggle(row, status) {
  const action = status === 1 ? '上架' : '下架'
  await ElMessageBox.confirm(`确定${action}消息「${row.title}」?${status === 0 ? '下架后用户端不可见。' : ''}`, `${action}确认`, { type: 'warning' })
  await adminUpdateNotice(row.id, { status })
  ElMessage.success(`已${action}`)
  await load()
}

async function remove(row) {
  await ElMessageBox.confirm(
    `确定删除消息「${row.title}」?删除后所有用户的已读记录一并清除。`, '删除确认', { type: 'warning' })
  await adminDeleteNotice(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>
