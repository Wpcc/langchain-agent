<template>
  <div class="knowledge-page">
    <!-- Header -->
    <div class="page-header">
      <el-button text @click="router.push('/')">
        <el-icon><ArrowLeft /></el-icon>
        返回对话
      </el-button>
      <span class="page-title">
        <el-icon><Folder /></el-icon>
        知识库管理
      </span>
      <span />
    </div>

    <div class="page-body">
      <el-tabs v-model="activeTab" class="main-tabs">

        <!-- ── Tab 1: Document Management ── -->
        <el-tab-pane label="文档管理" name="docs">
          <div class="tab-actions">
            <el-upload
              :show-file-list="false"
              :before-upload="handleUpload"
              accept=".txt,.pdf"
              :disabled="uploading"
            >
              <el-button type="primary" :loading="uploading" :icon="Upload">
                上传文档
              </el-button>
            </el-upload>

            <el-button
              :loading="indexing"
              :icon="Refresh"
              @click="handleIndex"
            >
              建立索引
            </el-button>

            <el-button :icon="RefreshRight" circle @click="loadDocs" />
          </div>

          <el-table
            v-loading="loadingDocs"
            :data="docs"
            stripe
            style="width: 100%; margin-top: 12px"
            empty-text="暂无文档，请上传 TXT 或 PDF 文件"
          >
            <el-table-column prop="filename" label="文件名" min-width="180">
              <template #default="{ row }">
                <el-icon style="margin-right:6px; color:#409eff"><Document /></el-icon>
                {{ row.filename }}
              </template>
            </el-table-column>

            <el-table-column prop="size_kb" label="大小" width="100" align="right">
              <template #default="{ row }">{{ row.size_kb }} KB</template>
            </el-table-column>

            <el-table-column label="状态" width="110" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.indexed" type="success" size="small">已索引</el-tag>
                <el-tag v-else type="warning" size="small">待索引</el-tag>
              </template>
            </el-table-column>

            <el-table-column prop="chunks" label="向量块数" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.indexed">{{ row.chunks }}</span>
                <span v-else style="color:#c0c4cc">—</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-popconfirm
                  :title="`确认删除「${row.filename}」？此操作将同时清除其向量数据。`"
                  confirm-button-text="删除"
                  cancel-button-text="取消"
                  confirm-button-type="danger"
                  width="240"
                  @confirm="handleDelete(row.filename)"
                >
                  <template #reference>
                    <el-button type="danger" text size="small" :icon="Delete">删除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ── Tab 2: Retrieval Test ── -->
        <el-tab-pane label="检索测试" name="test">
          <div class="test-input">
            <el-input
              v-model="testQuery"
              placeholder="输入检索词，测试完整 BM25 + 向量 + 重排序 流程"
              clearable
              @keydown.enter="handleTestRetrieval"
            />
            <el-button
              type="primary"
              :loading="testing"
              :icon="Search"
              @click="handleTestRetrieval"
              :disabled="!testQuery.trim()"
            >
              测试检索
            </el-button>
          </div>

          <template v-if="retrieval">
            <!-- Query rewrite info -->
            <el-alert
              v-if="retrieval.rewritten_query !== retrieval.original_query"
              type="info"
              :closable="false"
              style="margin: 16px 0 8px"
            >
              <template #title>
                <span>查询改写：</span>
                <el-tag size="small" style="margin: 0 6px">{{ retrieval.original_query }}</el-tag>
                <el-icon><Right /></el-icon>
                <el-tag size="small" type="success" style="margin: 0 6px">{{ retrieval.rewritten_query }}</el-tag>
              </template>
            </el-alert>
            <el-alert
              v-else
              type="success"
              :closable="false"
              title="查询无需改写，直接检索"
              style="margin: 16px 0 8px"
            />

            <!-- Result chunks -->
            <div v-if="retrieval.chunks.length === 0" class="empty-result">
              <el-empty description="未检索到相关内容，请尝试其他关键词" />
            </div>

            <div v-else class="chunk-list">
              <div
                v-for="chunk in retrieval.chunks"
                :key="chunk.rank"
                class="chunk-card"
              >
                <div class="chunk-header">
                  <el-tag type="primary" size="small"># {{ chunk.rank }}</el-tag>
                  <span class="chunk-source">
                    <el-icon><Document /></el-icon>
                    {{ chunk.source }}
                  </span>
                </div>
                <p class="chunk-content">{{ chunk.content }}</p>
              </div>
            </div>
          </template>

          <el-empty
            v-else-if="!testing"
            description="输入检索词后点击「测试检索」查看结果"
            style="margin-top: 40px"
          />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, Folder, Upload, Refresh, RefreshRight,
  Delete, Document, Search, Right,
} from '@element-plus/icons-vue'
import {
  listDocuments, uploadDocument, indexDocuments,
  deleteDocument, testRetrieval,
  type DocumentInfo, type RetrievalResult,
} from '@/api/knowledge'

const router = useRouter()
const activeTab = ref('docs')

// ── Document management ───────────────────────────────────────────────────
const docs = ref<DocumentInfo[]>([])
const loadingDocs = ref(false)
const uploading = ref(false)
const indexing = ref(false)

async function loadDocs() {
  loadingDocs.value = true
  try {
    const res = await listDocuments()
    docs.value = res.data
  } catch {
    ElMessage.error('加载文档列表失败')
  } finally {
    loadingDocs.value = false
  }
}

async function handleUpload(file: File) {
  uploading.value = true
  try {
    const res = await uploadDocument(file)
    ElMessage.success(res.data.message)
    await loadDocs()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '上传失败')
  } finally {
    uploading.value = false
  }
  return false // prevent el-upload default behaviour
}

async function handleIndex() {
  indexing.value = true
  try {
    const res = await indexDocuments()
    ElMessage.success(res.data.message)
    await loadDocs()
  } catch {
    ElMessage.error('索引构建失败')
  } finally {
    indexing.value = false
  }
}

async function handleDelete(filename: string) {
  try {
    await deleteDocument(filename)
    ElMessage.success(`已删除「${filename}」`)
    await loadDocs()
  } catch {
    ElMessage.error('删除失败')
  }
}

// ── Retrieval test ────────────────────────────────────────────────────────
const testQuery = ref('')
const testing = ref(false)
const retrieval = ref<RetrievalResult | null>(null)

async function handleTestRetrieval() {
  if (!testQuery.value.trim()) return
  testing.value = true
  retrieval.value = null
  try {
    const res = await testRetrieval(testQuery.value.trim())
    retrieval.value = res.data
  } catch {
    ElMessage.error('检索测试失败，请确认后端服务正常运行')
  } finally {
    testing.value = false
  }
}

onMounted(loadDocs)
</script>

<style scoped>
.knowledge-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: #303133;
}

.page-body {
  flex: 1;
  padding: 24px;
  max-width: 1000px;
  width: 100%;
  margin: 0 auto;
}

.main-tabs {
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px 24px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}

.tab-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 4px;
}

/* Retrieval test */
.test-input {
  display: flex;
  gap: 10px;
  margin-bottom: 8px;
}
.test-input .el-input { flex: 1; }

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 8px;
}

.chunk-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 14px 16px;
  background: #fafafa;
}

.chunk-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.chunk-source {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #909399;
}

.chunk-content {
  margin: 0;
  font-size: 14px;
  line-height: 1.75;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-result { margin-top: 24px; }
</style>
