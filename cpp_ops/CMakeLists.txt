cmake_minimum_required(VERSION 3.16)
project(pcl_pointcloud_ops_batch LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(PCL REQUIRED COMPONENTS common filters io)

add_executable(pcl_pointcloud_ops_batch
  src/pcl_pointcloud_ops.cpp
  src/csv_io.cpp
)

target_include_directories(pcl_pointcloud_ops_batch PRIVATE src ${PCL_INCLUDE_DIRS})
target_link_libraries(pcl_pointcloud_ops_batch PRIVATE ${PCL_LIBRARIES})
