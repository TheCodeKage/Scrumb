package com.yourname.projectcoach

import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.ComboBox
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.JBColor
import com.intellij.ui.components.*
import com.intellij.ui.content.ContentFactory
import com.intellij.util.ui.JBUI
import retrofit2.Call
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.awt.BorderLayout
import java.awt.Component
import java.awt.Dimension
import javax.swing.*

class CoachToolWindowFactory : ToolWindowFactory {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val state = CoachService.getInstance(project).state

        val retrofit = Retrofit.Builder()
            .baseUrl("https://api.scrumb.in")
            .addConverterFactory(GsonConverterFactory.create())
            .build()
        val api = retrofit.create(CoachApi::class.java)

        val mainPanel = JBPanel<JBPanel<*>>(BorderLayout())
        mainPanel.border = JBUI.Borders.empty(10)

        val progressBar = JProgressBar(0, 100).apply {
            isStringPainted = true
            alignmentX = Component.LEFT_ALIGNMENT


            


        }
// hy
        val scrollPanel = JBPanel<JBPanel<*>>().apply { layout = BoxLayout(this, BoxLayout.Y_AXIS) }

        // --- 1. Project Setup UI ---
        val nameField = JBTextField(state.projectName).apply { emptyText.text = "Project Name" }
        val descField = JBTextArea(3, 20).apply {
            lineWrap = true
            wrapStyleWord = true
            emptyText.text = "Description..."
        }
        val dateField = JBTextField().apply { emptyText.text = "End Date (YYYY-MM-DD)" }
        val createBtn = JButton("Initialize Project")
        val statusLabel = JBLabel("ID: ${state.currentProjectId ?: "None"}")

        // --- 2. Task & Session UI ---
        val taskListPanel = JBPanel<JBPanel<*>>().apply { layout = BoxLayout(this, BoxLayout.Y_AXIS) }
        val generateBtn = JButton("AI: Generate Plan").apply { isEnabled = state.currentProjectId != null }
        val startBtn = JButton("Start Session").apply { isEnabled = state.currentProjectId != null }
        val timerLabel = JBLabel("Session: ⚪ Idle")

        fun refreshTasks() {
            state.currentProjectId?.let { pid ->
                api.getProjectTasks(pid).enqueue(object : retrofit2.Callback<ProjectContext> {
                    override fun onResponse(call: Call<ProjectContext>, response: Response<ProjectContext>) {
                        val context = response.body() ?: return
                        SwingUtilities.invokeLater {
                            // Logic: Use the backend's definitive percentage
                            progressBar.value = context.completion_percentage.toInt()
                            progressBar.string = "${context.completion_percentage}%"

                            // Logic: Build the Tooltip with Daily Velocity
                            context.health?.let { health ->
                                val tooltipText = """
                                    <html>
                                    <div style='padding: 5px;'>
                                    <b>Project Health:</b> ${health.status}<br>
                                    <b>Daily Velocity:</b> ${health.daily_velocity}<br>
                                    <b>Panic Requirement:</b> ${health.current_panic_requirement}<br>
                                    <b>Expected Completion:</b> ${health.expected_complete_in}
                                    </div>
                                    </html>
                                """.trimIndent()
                                progressBar.toolTipText = tooltipText
                            }

                            // 1. Logic: Clear the list
                            taskListPanel.removeAll()

                            // 2. Logic: Define addRecursive BEFORE calling it to resolve the error
                            fun addRecursive(tasks: List<ApiTask>, depth: Int) {
                                tasks.forEach { task ->
                                    val taskRow = JBPanel<JBPanel<*>>(BorderLayout())
                                    taskRow.border = JBUI.Borders.empty(2, depth * 20, 2, 5)
                                    taskRow.alignmentX = Component.LEFT_ALIGNMENT

                                    taskRow.add(JBLabel(task.title), BorderLayout.CENTER)

                                    val statusOptions = arrayOf("to-do", "doing", "done")
                                    val statusDropdown = ComboBox(statusOptions).apply {
                                        selectedItem = task.status
                                        preferredSize = Dimension(90, 25)

                                        addActionListener {
                                            val newStatus = selectedItem as String
                                            api.updateTaskStatus(task.id, mapOf("status" to newStatus)).enqueue(object : retrofit2.Callback<Map<String, Any>> {
                                                override fun onResponse(call: Call<Map<String, Any>>, res: Response<Map<String, Any>>) {
                                                    if (res.isSuccessful) {
                                                        SwingUtilities.invokeLater { refreshTasks() }
                                                    } else if (res.code() == 400) {
                                                        SwingUtilities.invokeLater {
                                                            JOptionPane.showMessageDialog(null, "Complete sub-tasks first!")
                                                            selectedItem = "doing"
                                                        }
                                                    }
                                                }
                                                override fun onFailure(call: Call<Map<String, Any>>, t: Throwable) {}
                                            })
                                        }
                                    }
                                    taskRow.add(statusDropdown, BorderLayout.EAST)
                                    taskListPanel.add(taskRow)

                                    val subList = task.subtasks ?: emptyList()
                                    if (subList.isNotEmpty()) {
                                        addRecursive(subList, depth + 1)
                                    }
                                }
                            }

                            // 3. Logic: Now call the function
                            addRecursive(context.tasks, 0)

                            // Logic: Final UI Refresh
                            taskListPanel.revalidate()
                            taskListPanel.repaint()
                        }
                    }
                    override fun onFailure(call: Call<ProjectContext>, t: Throwable) {}
                })
            }
        }

        // --- 3. Button Logic ---
        createBtn.addActionListener {
            val req = ProjectRequest(nameField.text, descField.text ,dateField.text  )
            api.createProject(req).enqueue(object : retrofit2.Callback<ProjectResponse> {
                override fun onResponse(call: retrofit2.Call<ProjectResponse>, response: retrofit2.Response<ProjectResponse>) {
                    response.body()?.id?.let { id ->
                        state.currentProjectId = id
                        state.projectName = nameField.text
                        SwingUtilities.invokeLater {
                            statusLabel.text = "ID: $id"
                            generateBtn.isEnabled = true
                            startBtn.isEnabled = true
                            JOptionPane.showMessageDialog(null, "Project Created!")
                        }
                    }
                }
                override fun onFailure(call: retrofit2.Call<ProjectResponse>, t: Throwable) {}
            })
        }

        generateBtn.addActionListener {
            state.currentProjectId?.let { id ->
                api.generatePlan(id).enqueue(object : retrofit2.Callback<Map<String, String>> {
                    override fun onResponse(call: retrofit2.Call<Map<String, String>>, response: retrofit2.Response<Map<String, String>>) {
                        SwingUtilities.invokeLater {
                            JOptionPane.showMessageDialog(null, "AI Plan Started! Refreshing tasks...")
                            refreshTasks()
                        }
                    }
                    override fun onFailure(call: retrofit2.Call<Map<String, String>>, t: Throwable) {}
                })
            }
        }

        // --- 4. Assembly ---
        scrollPanel.add(JBLabel("🚀 Project Setup").apply { font = font.deriveFont(14f) })
        scrollPanel.add(nameField)
        scrollPanel.add(JBScrollPane(descField))
        scrollPanel.add(dateField)
        scrollPanel.add(createBtn)
        scrollPanel.add(statusLabel)
        scrollPanel.add(JSeparator().apply { border = JBUI.Borders.empty(10, 0) })

        scrollPanel.add(generateBtn)
        scrollPanel.add(progressBar)
        scrollPanel.add(timerLabel)
        scrollPanel.add(startBtn)

        scrollPanel.add(JBLabel("📅 Tasks & Subtasks:").apply { border = JBUI.Borders.empty(10, 0) })

        val taskScroll = JBScrollPane(taskListPanel).apply {
            preferredSize = Dimension(280, 400)
            border = JBUI.Borders.customLine(JBUI.CurrentTheme.CustomFrameDecorations.separatorForeground(), 1)
        }
        scrollPanel.add(taskScroll)

        mainPanel.add(JBScrollPane(scrollPanel), BorderLayout.CENTER)
        toolWindow.contentManager.addContent(ContentFactory.getInstance().createContent(mainPanel, "Scrum-in", false))

        if (state.currentProjectId != null) refreshTasks()
    }
}