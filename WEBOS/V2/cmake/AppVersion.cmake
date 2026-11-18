# The app's version is appinfo.json's (what the TV shows and the .ipk is named after); the release
# workflow writes the tag into it before building. Sets DRPS5_VERSION.
file(READ "${CMAKE_CURRENT_LIST_DIR}/../appinfo.json" _drps5_appinfo)
string(REGEX MATCH "\"version\"[ \t]*:[ \t]*\"([^\"]+)\"" _drps5_match "${_drps5_appinfo}")
if(NOT CMAKE_MATCH_1)
    message(FATAL_ERROR "appinfo.json has no \"version\"")
endif()
set(DRPS5_VERSION "${CMAKE_MATCH_1}")
