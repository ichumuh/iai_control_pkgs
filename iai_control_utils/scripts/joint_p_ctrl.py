#!/usr/bin/env python
#
#    Simple boxy joint controller
#
#    Copyright (c) 2014 Universitaet Bremen - Institute for Artificial Intelligence (Prof. Beetz)
#    Authors: Alexis Maldonado  <amaldo@cs.uni-bremen.de>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Simple idea, read on the joint_state topic, and for each message received, answer with des velocities

import roslib; roslib.load_manifest('realtime_bridge')
import rospy
from rospy.numpy_msg import numpy_msg
import numpy

from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray

#The supported velocity output types:
from iai_control_msgs.msg import MultiJointVelocityImpedanceCommand
from iai_control_msgs.msg import MultiJointVelocityCommand

        
        
class JController(object):
    """Simple Position joint-array controller (Output: Velocity)"""
    def __init__(self, vel_output_topic_type, max_speed, ctrl_p, def_stiffness):
        
        #Variable that checks if we can start working
        self.configured = False
        
        #Will only start controlling after receiving at least one desired position
        self.received_des_pos_values = False
        self.def_stiffness = def_stiffness
	
        #Controller parameters
        self.ctrl_p = ctrl_p
        self.max_speed = max_speed
        
        self.num_dof = 0;
        self.init_work_variables()
        
        #Chose the appropriate topic type
        if (vel_output_topic_type == 'MultiJointVelocityImpedanceCommand'):
            self.vel_output_topic_type = MultiJointVelocityImpedanceCommand
        elif (vel_output_topic_type == 'MultiJointVelocityCommand'):
            self.vel_output_topic_type = MultiJointVelocityCommand
        else:
            rospy.logfatal('%s: Velocity output topic type not supported. Extend the JController class if you want to support output to a topic of type %s.' %(rospy.get_name(), vel_output_topic_type))
            raise Exception('should_exit')

        self.vel_pub = rospy.Publisher("~vel_command_out", numpy_msg(self.vel_output_topic_type), queue_size=3, tcp_nodelay=True, latch=False)   
        self.js_sub = rospy.Subscriber("~joint_states", numpy_msg(JointState), self.js_cb, queue_size=3, tcp_nodelay=True)
        self.js_des_pos = rospy.Subscriber("~pos_command_in", numpy_msg(Float32MultiArray), self.des_pos_cb, queue_size=3, tcp_nodelay=True)
            
        
        
    def init_work_variables(self):
        self.des_pos = numpy.array([0.0] * self.num_dof, dtype=numpy.float32)      
        self.actual_pos = numpy.array([0.0] * self.num_dof, dtype=numpy.float32)
        self.error = numpy.array([0.0] * self.num_dof, dtype=numpy.float32)
        
        
    def set_num_dof(self, num_dof):
        if not self.configured:
            self.num_dof = num_dof
            self.init_work_variables()
            self.configured = True
        else:
            rospy.logerr('%s: Tried to change number of DOF, will ignore.' %(rospy.get_name()))
        
        
    def stop(self):
        ''''Stop the joint controller. Send zero velocities before going out. The watchdog should kick in, but just in case'''
        rospy.loginfo('%s: Stopping the P controller. Sending a last velocity command of zero.' %(rospy.get_name()))
        self.js_sub.unregister()
        self.js_des_pos.unregister()

        out_msg = self.vel_output_topic_type()
        out_msg.velocity = numpy.array([0.0] * self.num_dof, dtype=numpy.float32)
	out_msg.header.stamp = rospy.Time.now()
        self.vel_pub.publish(out_msg)
        
        #Sleep a little to try to get that last message published before dying
        rospy.sleep(0.5)
        self.vel_pub.unregister()  #will happen when the node is dying anyway
        
        
    def js_cb(self, msg):
        '''Callback function that receives the current state of the joints.
           The first time it is called, it configures the number of DOF.
           It calls control_tick() once for each received joint_state.'''

        if not self.configured:
            #The first time that we receive joint_states, we set the number of DOF
            num_dof = len(msg.name)
            rospy.loginfo('%s: Setting Num DOF to %d' % (rospy.get_name(), num_dof))
            self.set_num_dof(num_dof)
            
        #check length
        if (len(msg.position) == self.num_dof):
            #print type(msg.position)
            self.actual_pos = msg.position
            self.control_tick()
            
    def control_tick(self):
        '''Do one iteration of the controller. For now, a simple P controller'''
        
        #Only work when the necessary information is available
        if self.received_des_pos_values and self.configured:
            self.error = self.des_pos - self.actual_pos
            vel_out = self.error * self.ctrl_p
            vel_out = numpy.clip(vel_out, -self.max_speed, self.max_speed)
            
        else:
            #If not ready, just transmit zero velocities
            vel_out = numpy.array([0.0] * self.num_dof, dtype=numpy.float32)


        if (self.vel_pub.get_num_connections() > 0):
            #Publish the message
            out_msg = self.vel_output_topic_type()
            out_msg.velocity = vel_out
	    
            if (self.vel_output_topic_type() == 'MultiJointVelocityImpedanceCommand'):
                out_msg.stiffness = [self.def_stiffness] * self.num_dof
	    out_msg.header.stamp = rospy.Time.now()
            self.vel_pub.publish(out_msg)
            
            
            
    def des_pos_cb(self, msg):
        '''Callback function that received the desired joint positions for the controller'''
        #FIXME: More sanity checks on the input data?
        
        if len(msg.data) == self.num_dof:
            #print type(msg.data)
            self.des_pos = msg.data
            
            if not self.received_des_pos_values:
                        rospy.loginfo('%s: Received first joint position goal. Will start working' %(rospy.get_name()))
                        self.received_des_pos_values = True
                                
            
        else:
            rospy.logwarn('%s: Received desired position with non-matching number of joints. Ignoring.' % (rospy.get_name()))


def main():
    rospy.init_node('boxy_joint_controller', anonymous=False)
    rospy.loginfo("%s: Starting" % (rospy.get_name()))

    #Read the parameters for configuration
    vel_output_topic_type = rospy.get_param('~vel_command_type', 'MultiJointVelocityImpedanceCommand')
    max_speed = rospy.get_param('~max_speed', 0.3) #rads/s
    stiffness = rospy.get_param('~stiffness', 100) #Nm/m
    
    p_gain = rospy.get_param('~p_gain', 3.5) #P constant of the P controller

    rospy.loginfo('%s: max_speed=%f p_gain=%f' %(rospy.get_name(), max_speed, p_gain))
    #Instantiate the controller class (starts on its own)
    cont = JController(vel_output_topic_type, max_speed, p_gain, stiffness)

    
    #Register function to call when stopping (to stop the motors)
    rospy.on_shutdown(cont.stop)
    
    #r = rospy.Rate(1)
    #while not rospy.is_shutdown():
    #    #Publish diagnostics at slow rate
    #    pass
    #    r.sleep()
    
    #Block until the ROS node is shut down. Let the other threads do the work.
    rospy.spin()
                
    rospy.loginfo("%s: Exiting" % (rospy.get_name()))
        
    
    

if __name__ == '__main__':
    main()
    
