package com.yourname.projectcoach

import com.google.gson.annotations.SerializedName
import com.jetbrains.rd.generator.nova.PredefinedType
import kotlinx.datetime.LocalDate
import retrofit2.Call
import retrofit2.http.*

data class ProjectRequest(val name: String, val description: String ,val guarantee_date: String)
data class ProjectResponse(val id: String)
data class SessionResponse(val session_id: String)

data class ProjectContext(
    val id: String,
    val name: String,
    val tasks: List<ApiTask>,
    val completion_percentage: Double,
     // Daily velocity for progress bar string
    val health: ProjectHealth?
     // Health object for tooltips
)
data class ProjectHealth(
    val status: String,
    val daily_velocity: Double,
    val current_panic_requirement: String,
    val expected_complete_in: String
)

// Logic: Nested model to support AI-generated subtasks
data class ApiTask(
    val id: Int,
    val title: String,
    @SerializedName("status") val status: String,
    // Logic: Map backend 'sub_tasks' to Kotlin 'subtasks' and ensure it's never null
    @SerializedName("sub_tasks") val subtasks: List<ApiTask>? = emptyList()
) {
    // Helper logic to safely check if a task is "done" based on backend status
    val isCompleted: Boolean get() = status == "completed"
}

interface CoachApi {
    @POST("/project/")
    fun createProject(@Body data: ProjectRequest): Call<ProjectResponse>

    @POST("/api/session/start/")
    fun startSession(@Query("project_id") projectId: String): Call<SessionResponse>

    @POST("/project/{id}/generate_plan/")
    fun generatePlan(@Path("id") id: String): Call<Map<String, String>>

    @GET("/project/{id}")
    fun getProjectTasks(@Path("id") id: String): Call<ProjectContext>

    @FormUrlEncoded
    @POST("/api/task/complete/")
    fun completeTask(
        @Field("task_id") taskId: Int,
        @Field("session_id") sessionId: String
    ): Call<Map<String, String>>

    @PATCH("/task/{id}/")
    fun updateTaskStatus(
        @Path("id") taskId: Int,
        @Body statusUpdate: Map<String, String>
    ): Call<Map<String, Any>>
}