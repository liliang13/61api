<template>
  <div class="min-h-screen bg-white pt-[64px]">
    <SiteNav />
    <div class="mx-auto max-w-3xl px-4 py-12">
      <h1 class="text-3xl font-bold text-stone-800">隐私政策</h1>
      <p class="mt-2 text-xs text-stone-400">最近更新:2026 年 10 月 · 河北小柠科技有限公司</p>
      <div class="mt-8 space-y-8 text-sm leading-7 text-stone-600">
        <section>
          <h2 class="mb-2 font-bold text-stone-800">我们收集哪些信息</h2>
          <ul class="list-disc space-y-1 pl-5">
            <li><b>账号信息</b>:手机号(注册与登录验证必需)、密码(仅存储加盐哈希)。</li>
            <li><b>使用信息</b>:API 调用记录(模型、Token 用量、耗时、调用渠道)用于计费与明细展示;登录/注册的 IP 地址与时间用于安全审计。</li>
            <li><b>订单信息</b>:充值订单号、金额、支付状态;开票时的抬头、税号与接收邮箱。</li>
          </ul>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">我们如何使用信息</h2>
          <ul class="list-disc space-y-1 pl-5">
            <li>提供账号、计费、发票与客户支持服务;</li>
            <li>防范刷量、欺诈与滥用(设备风险验证、频率限制、邀请反作弊);</li>
            <li>依法履行义务(如税务、司法机关的合法要求)。</li>
          </ul>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">第三方服务与信息处理</h2>
          <p class="mb-2">我们不出售您的个人信息。为完成安全验证、通信、支付和模型调用,以下第三方会在必要范围内处理相关信息:</p>
          <ul class="list-disc space-y-1 pl-5">
            <li><b>阿里云人机验证</b>:用于识别异常注册、登录及发码请求,可能处理设备特征、网络信息、验证行为和验证结果。</li>
            <li><b>阿里云短信</b>:用于发送注册、登录、绑定及重置密码验证码,会处理您的手机号、验证码发送记录及必要的网络信息。</li>
            <li><b>支付服务机构</b>:支付宝、微信支付用于完成充值,会处理订单号、金额、支付状态及支付所需的交易信息。</li>
            <li><b>上游模型服务商</b>:为返回模型结果,会接收您提交的模型请求内容、参数及用量信息;我们不会主动向其提供本站账号密码或手机号。</li>
          </ul>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">存储与保护</h2>
          <p>数据存储于中国境内服务器,数据库文件与密钥配置仅限服务进程访问,并采取严格的访问控制。API 密钥完整明文仅在创建时返回一次,之后不可查阅。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">您的权利</h2>
          <p>您可联系我们注销账号、删除非必需历史数据(依法需留存的财务记录除外)。</p>
        </section>
        <section>
          <h2 class="mb-2 font-bold text-stone-800">联系我们</h2>
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
