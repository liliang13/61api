<template>
  <div class="min-h-screen bg-white pt-[64px]">
    <SiteNav />
    <div class="mx-auto max-w-3xl px-4 py-12">
      <h1 class="text-3xl font-bold text-stone-800">服务条款</h1>
      <p class="mt-2 text-xs text-stone-400">最近更新:2026 年 10 月 · 河北小柠科技有限公司</p>
      <div class="mt-8 space-y-8 text-sm leading-7 text-stone-600">
        <section>
          <h2 class="mb-2 font-bold text-stone-800">1. 服务内容</h2>
          <p>61API(本站)提供大模型 API 聚合转发服务。用户注册账号、创建 API 密钥后,可通过本站提供的接口调用已上架的模型,按实际用量计费。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">2. 账号与密钥</h2>
          <p>注册需提供手机号并通过短信验证。API 密钥完整内容仅在创建时展示一次,请自行妥善保管;因密钥保管不善造成的损失由用户自行承担,发现泄露请立即在控制台禁用并重建。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">3. 计费与退款</h2>
          <p>计费以人民币结算,按各模型单价与实际 Token 用量实时扣费,控制台提供逐笔明细与复算公式。充值余额长期有效。<b>已申请开票的充值订单不可退款</b>;未开票订单可在合理期限内联系客服协商退款。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">4. 使用规范</h2>
          <p>禁止利用本服务从事法律法规禁止的活动,包括但不限于:生成违法有害内容、攻击性爬取、恶意刷量、转售干扰服务正常运转的行为。违反者我们有权封禁账号且不予退款。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">5. 服务可用性</h2>
          <p>我们采用多渠道自动切换等手段保障可用性,但不承诺服务不中断;上游模型服务商的变更、限流或故障可能影响部分模型调用,此类情况失败请求不计费。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">6. 免责声明</h2>
          <p>模型输出内容由人工智能生成,我们不对其准确性、完整性作担保,重要决策请自行核实。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">7. 联系我们</h2>
          <p>contact@xiaoningkeji.com</p>
        </section>
      </div>
    </div>
    <SiteFooter />
  </div>
</template>

<script setup>
import SiteNav from '../components/SiteNav.vue'
import SiteFooter from '../components/SiteFooter.vue'
</script>
