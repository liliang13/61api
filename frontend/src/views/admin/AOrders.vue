<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">充值订单</h1>
    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="created_at" label="时间" width="165" />
        <el-table-column prop="order_no" label="订单号" min-width="230">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.order_no }}</code></template>
        </el-table-column>
        <el-table-column prop="user_id" label="用户ID" width="80" align="center" />
        <el-table-column label="金额" width="100" align="right">
          <template #default="{ row }">¥{{ (row.amount / 100).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="到账额度" width="100" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="95" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="{ paid: 'success', pending: 'warning', refunded: 'info' }[row.status]">
              {{ { paid: '已到账', pending: '待支付', refunded: '已退款' }[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'paid'" link type="danger" size="small" @click="refund(row)">退款</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminOrders, adminRefundOrder } from '../../api'
import { dialogResult } from '../../utils/dialog'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 20

async function load() {
  const res = await adminOrders({ page: page.value, page_size: size })
  items.value = res.data.items
  total.value = res.data.total
}

async function refund(row) {
  if (!await dialogResult(ElMessageBox.confirm(
    `确定退款订单 ${row.order_no}?用户余额将扣回 ¥${(row.quota / 500000).toFixed(2)}(余额不足会扣成负数)。`,
    '退款确认', { type: 'warning' }))) return
  await adminRefundOrder(row.order_no)
  ElMessage.success('已退款')
  await load()
}

onMounted(load)
</script>
