package com.yourname.projectcoach

import com.intellij.openapi.components.*
import com.intellij.openapi.project.Project
import com.intellij.util.xmlb.annotations.XCollection

class SessionData {
    var sessionNumber: Int = 0
    var durationSeconds: Int = 0
    var startTime: Long = System.currentTimeMillis()

    // Logic: This is how the session will look in the list
    override fun toString(): String {
        val mins = durationSeconds / 60
        val secs = durationSeconds % 60
        return "Session #$sessionNumber: ${mins}m ${secs}s"
    }
}

class CoachState {
    @XCollection(style = XCollection.Style.v2)
    var currentProjectId: String? = null
    var currentSessionId: String? = null
    var projectName: String = ""

    // Keep these if you still want to track the local tasks


    var allSessions: MutableList<SessionData> = mutableListOf()
    var streakDays: Int = 3
    var task1Completed: Boolean = false
    var task2Completed: Boolean = false
    var task3Completed: Boolean = false
    var totalSeconds: Int = 0
}

@Service(Service.Level.PROJECT)
@State(name = "ProjectCoachState", storages = [Storage("projectCoach.xml")])
class CoachService : PersistentStateComponent<CoachState> {
    private var myState = CoachState()
    override fun getState(): CoachState = myState
    override fun loadState(state: CoachState) { myState = state }
    companion object {
        fun getInstance(project: Project): CoachService = project.getService(CoachService::class.java)
    }
}